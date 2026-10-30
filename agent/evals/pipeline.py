"""The eval pipeline: load+validate -> integrity -> SUT -> deterministic metrics -> DeepEval -> Ragas -> aggregate ->
regression gate -> reports.  Library entry point: `run_pipeline(RunConfig(...))`; CLI: `python -m evals.run`.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from evals import __version__
from evals.common import (BASELINES_DIR, FAKE_BANNER, GOLDEN_PATH, RESULTS_DIR, THRESHOLDS_PATH, mean, new_run_id,
                          now_iso, pct, read_json, write_json)
from evals.dataset import CATEGORIES, Case, Dataset, dataset_hash, load_dataset
from evals.metrics_det import (DETERMINISTIC_METRICS, MetricResult, aggregate_trials, cost_per_solve, evaluate_trace,
                               guard_rates, tokens_per_solve)
from evals.sut import LiveUnavailable, SutContext, Trace, preflight, run_case

SUITES: dict[str, list[str] | None] = {
    "all": None,
    "bugs": ["bug_fix_single_file"],
    "repo": ["bug_fix_multi_file", "pr_quality", "followup_change_request"],
    "multi": ["bug_fix_multi_file"],
    "safety": ["safety_guardrails"],
    "locator": ["locator_retrieval"],
    "repro": ["reproducer_quality"],
    "unsolvable": ["unsolvable_or_underspecified"],
    "followup": ["followup_change_request"],
    "pr": ["pr_quality"],
    "quick": None,
}
QUICK_IDS = ["bf-paginate", "bf-lru-cache", "bf-shop-api-coupon", "loc-wordstats-distractor", "saf-injection-print-env",
             "unsol-false-bug-report", "fu-shop-add-comment", "pr-booking-closes-issue"]
STAGES = ("dataset", "integrity", "sut", "metrics", "deepeval", "ragas", "aggregate", "gate", "report")
HEADLINE_HIGHER_BETTER = ("solve_rate", "pass_at_k", "guard_tpr", "guard_accuracy", "honest_failure_rate")


@dataclass
class RunConfig:
    mode: str = "fake"
    engine: str = "graph"
    suite: str = "all"
    case_ids: list[str] = field(default_factory=list)
    n: int = 1
    concurrency: int = 4
    timeout: float = 120.0
    judge: str = "none"  # none | nebius
    baseline: str = ""  # "" = default per-mode baseline; "none"; "latest"; run id; path
    update_baseline: bool = False
    run_id: str = ""
    resume: str = ""  # run id whose traces are reused
    results_dir: Path = RESULTS_DIR
    dataset_path: Path = GOLDEN_PATH
    fake_delay_scale: float = 0.05
    integrity: bool = True
    deepeval: bool = True
    ragas: bool = True
    thresholds_path: Path = THRESHOLDS_PATH
    write: bool = True


Progress = Callable[[str, int, int, str], None]


def select_cases(ds: Dataset, suite: str = "all", case_ids: list[str] | None = None) -> list[Case]:
    if case_ids:
        by = ds.by_id()
        missing = [c for c in case_ids if c not in by]
        if missing:
            raise ValueError(f"unknown case ids: {missing}")
        return [by[c] for c in case_ids]
    cats: set[str] = set()
    ids: list[str] | None = None
    for part in [p.strip() for p in suite.split(",") if p.strip()]:
        if part == "quick":
            ids = (ids or []) + QUICK_IDS
        elif part in SUITES and SUITES[part] is None:
            return list(ds.cases)
        elif part in SUITES:
            cats.update(SUITES[part] or [])
        elif part in CATEGORIES:
            cats.add(part)
        else:
            raise ValueError(f"unknown suite {part!r}; use one of {sorted(SUITES)} or a category name")
    return [c for c in ds.cases if c.category in cats or (ids and c.id in ids)]


# ---- aggregation --------------------------------------------------------------------------------------

def _agg(values: list[MetricResult]) -> dict[str, Any]:
    ok = [v for v in values if v.applicable]
    passes = [v.passed for v in ok if v.passed is not None]
    return {"mean": mean([v.score for v in ok]), "n": len(ok), "min": min((v.score for v in ok), default=None),
            "pass_rate": (sum(passes) / len(passes)) if passes else None,
            "higher_is_better": ok[0].higher_is_better if ok else True}


def aggregate(cases: list[Case], per_case: dict[str, dict[str, MetricResult]], traces: dict[str, list[Trace]]
              ) -> dict[str, Any]:
    names = list(dict.fromkeys(n for m in per_case.values() for n in m))
    by_id = {c.id: c for c in cases}

    def group(key: Callable[[Case], str] | None) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[str]] = {}
        for cid in per_case:
            groups.setdefault(key(by_id[cid]) if key else "overall", []).append(cid)
        return {g: {n: _agg([per_case[c][n] for c in ids if n in per_case[c]]) for n in names}
                for g, ids in groups.items()}

    overall = group(None)["overall"]
    flat = [t for ts in traces.values() for t in ts]
    solved_cases = [c for c in cases if c.expected.solved and c.category != "reproducer_quality"]
    solves = sum(1 for c in solved_cases for t in traces.get(c.id, []) if t.solved)
    trials = sum(len(traces.get(c.id, [])) for c in solved_cases)
    guard_rows = [{"expected": r.details["expected"], "got": r.details["got"]}
                  for m in per_case.values() for r in [m.get("guard_accuracy")] if r and r.applicable
                  for _ in range(r.details.get("trials", 1))]
    gr = guard_rates(guard_rows)
    lat = [t.latency_ms for t in flat if t.status == "ok"]
    ttfe = [t.ttfe_ms for t in flat if t.ttfe_ms is not None]
    tokens = [float((t.usage or {}).get("total_tokens", 0) or 0) for t in flat]
    costs = [(t.usage or {}).get("cost_usd") for t in flat]
    headline = {
        "solve_rate": (solves / trials) if trials else None, "solves": solves, "solve_trials": trials,
        "pass_at_k": overall.get("pass_at_k", {}).get("mean"),
        "guard_tpr": gr["tpr"], "guard_fpr": gr["fpr"], "guard_accuracy": gr["accuracy"],
        "honest_failure_rate": overall.get("honest_failure", {}).get("mean"),
        "latency_p50_ms": pct(lat, 0.5), "latency_p95_ms": pct(lat, 0.95),
        "ttfe_p50_ms": pct(ttfe, 0.5) if ttfe else None, "ttfe_p95_ms": pct(ttfe, 0.95) if ttfe else None,
        "tokens_total": sum(tokens), "tokens_per_solve": tokens_per_solve(tokens, solves),
        "cost_per_solve_usd": cost_per_solve(costs, solves),
        "cost_total_usd": (sum(c for c in costs if c is not None) if any(c is not None for c in costs) else None),
    }
    return {"overall": overall, "by_category": group(lambda c: c.category),
            "by_difficulty": group(lambda c: c.difficulty), "headline": headline, "metric_names": names}


# ---- gate ---------------------------------------------------------------------------------------------------

def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def resolve_baseline(spec: str, mode: str, results_dir: Path) -> tuple[dict[str, Any] | None, str]:
    """(baseline dict, label). spec: '' default per-mode file, 'none', 'latest', a run id, or a path."""
    if spec == "none":
        return None, "none (disabled)"
    if spec in ("", "default"):
        p = BASELINES_DIR / f"{mode}-baseline.json"
        return (read_json(p), str(p.relative_to(BASELINES_DIR.parent))) if p.is_file() else (None, f"no {p.name}")
    if spec == "latest":
        idx = read_json(results_dir / "index.json", []) or []
        for row in idx:
            data = read_json(results_dir / row["run_id"] / "summary.json")
            if data and data.get("mode") == mode:
                return baseline_from_summary(data), f"run {row['run_id']}"
        return None, "no previous run for this mode"
    p = Path(spec)
    if p.is_file():
        data = read_json(p)
        return (data if data and "metrics" in data else baseline_from_summary(data or {})), str(p)
    data = read_json(results_dir / spec / "summary.json")
    return (baseline_from_summary(data), f"run {spec}") if data else (None, f"unknown baseline {spec!r}")


def baseline_from_summary(s: dict[str, Any]) -> dict[str, Any]:
    def means(block: dict[str, Any]) -> dict[str, float]:
        return {k: v["mean"] for k, v in block.items() if isinstance(v, dict) and v.get("mean") is not None}

    return {
        "baseline_version": 1, "run_id": s.get("run_id"), "created": s.get("created"), "mode": s.get("mode"),
        "engine": s.get("engine"), "dataset_version": s.get("dataset_version"), "cases": s.get("cases"),
        "metrics": {"overall": means(s.get("overall", {})),
                    "by_category": {c: means(b) for c, b in s.get("by_category", {}).items()},
                    "headline": {k: v for k, v in s.get("headline", {}).items() if isinstance(v, (int, float))}},
        "case_outcomes": s.get("case_outcomes", {}),
    }


def evaluate_gate(summary: dict[str, Any], baseline: dict[str, Any] | None, baseline_label: str,
                  thresholds: dict[str, Any]) -> dict[str, Any]:
    mode = summary["mode"]
    checks: list[dict[str, Any]] = []

    def value_of(metric: str, scope: str) -> float | None:
        if scope == "headline":
            return summary["headline"].get(metric)
        if scope == "overall":
            return (summary["overall"].get(metric) or {}).get("mean")
        if scope.startswith("category:"):
            return ((summary["by_category"].get(scope.split(":", 1)[1]) or {}).get(metric) or {}).get("mean")
        return None

    full_suite = summary.get("suite") == "all" and not summary.get("case_filter")
    for rule in (thresholds.get("absolute") or {}).get(mode, []):
        metric, scope = rule["metric"], rule.get("scope", "overall")
        v = value_of(metric, scope)
        if v is None:
            checks.append({"kind": "absolute", "metric": metric, "scope": scope, "ok": True, "skipped": True,
                           "message": "metric not applicable to the selected cases"})
            continue
        lo, hi = rule.get("min"), rule.get("max")
        ok = (lo is None or v >= lo - 1e-9) and (hi is None or v <= hi + 1e-9)
        bound = f">= {lo}" if lo is not None else f"<= {hi}"
        checks.append({"kind": "absolute", "metric": metric, "scope": scope, "value": v, "threshold": lo if lo is not None else hi,
                       "ok": ok, "message": f"{metric} ({scope}) = {v:.3f}, required {bound}"})

    reg = thresholds.get("regression") or {}
    if baseline is None:
        checks.append({"kind": "regression", "metric": "-", "scope": "-", "ok": True, "skipped": True,
                       "message": f"no baseline ({baseline_label}): regression gate skipped"})
    elif baseline.get("mode") and baseline["mode"] != mode:
        checks.append({"kind": "regression", "metric": "-", "scope": "-", "ok": True, "skipped": True,
                       "message": f"baseline was recorded in {baseline['mode']} mode, run is {mode}: skipped"})
    else:
        default_tol = reg.get("default_tolerance", 0.05)
        bm = baseline.get("metrics", {})
        for metric, rule in (reg.get("metrics") or {}).items():
            if rule.get("modes") and mode not in rule["modes"]:
                continue
            scope = rule.get("scope", "overall")
            cur = value_of(metric, scope)
            base = (bm.get("headline", {}) if scope == "headline" else bm.get("overall", {})).get(metric)
            if cur is None or base is None:
                continue
            tol = rule.get("tolerance", default_tol)
            if rule.get("relative"):
                tol = abs(base) * tol
            lower = rule.get("direction", "higher") == "lower"
            delta = cur - base
            ok = delta <= tol + 1e-9 if lower else delta >= -tol - 1e-9
            checks.append({"kind": "regression", "metric": metric, "scope": scope, "value": cur, "baseline": base,
                           "delta": delta, "tolerance": tol, "ok": ok,
                           "message": f"{metric} {base:.3f} -> {cur:.3f} (delta {delta:+.3f}, tolerance {tol:.3f}, "
                                      f"{'lower' if lower else 'higher'} is better)"})
        flips_allowed = (thresholds.get("case_flips") or {}).get("allowed", 0)
        prev = baseline.get("case_outcomes", {})
        now = summary.get("case_outcomes", {})
        flipped = sorted(c for c, v in prev.items() if v == 1 and c in now and now[c] == 0)
        checks.append({"kind": "case_flips", "metric": "case_outcomes", "scope": "cases", "ok": len(flipped) <= flips_allowed,
                       "value": len(flipped), "threshold": flips_allowed, "flipped": flipped,
                       "message": f"{len(flipped)} case(s) that matched expectations in the baseline no longer do"
                                  + (f": {', '.join(flipped)}" if flipped else "")})
    failed = [c for c in checks if not c["ok"]]
    return {"passed": not failed, "failed": len(failed), "checks": checks, "baseline": baseline_label,
            "full_suite": full_suite}


# ---- SUT stage -----------------------------------------------------------------------------------------------

def _trace_path(run_dir: Path, case_id: str, trial: int) -> Path:
    return run_dir / "traces" / f"{case_id}__{trial}.json"


async def _run_suts(cfg: RunConfig, cases: list[Case], run_dir: Path, resume_dir: Path | None,
                    progress: Progress | None) -> dict[str, list[Trace]]:
    ctx = SutContext(cfg.mode, cfg.engine, fake_delay_scale=cfg.fake_delay_scale)
    await ctx.start()
    sem = asyncio.Semaphore(max(1, cfg.concurrency))
    out: dict[str, list[Trace | None]] = {c.id: [None] * cfg.n for c in cases}
    jobs = [(c, t) for c in cases for t in range(cfg.n)]
    done = 0
    lock = asyncio.Lock()

    async def one(case: Case, trial: int) -> None:
        nonlocal done
        cached = None
        for d in (resume_dir, run_dir):
            if d and _trace_path(d, case.id, trial).is_file():
                data = read_json(_trace_path(d, case.id, trial))
                if data and data.get("mode") == cfg.mode and data.get("status") == "ok":
                    cached = Trace.from_dict(data)
                    break
        if cached is None:
            async with sem:
                cached = await run_case(ctx, case, trial, cfg.timeout)
            if cfg.write:
                write_json(_trace_path(run_dir, case.id, trial), cached.to_dict())
        out[case.id][trial] = cached
        async with lock:
            done += 1
            if progress:
                progress("sut", done, len(jobs), f"{case.id} #{trial}: {cached.status}")

    await asyncio.gather(*(one(c, t) for c, t in jobs))
    return {k: [t for t in v if t is not None] for k, v in out.items()}


# ---- main ---------------------------------------------------------------------------------------------------

def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                              cwd=Path(__file__).parent).stdout.strip()
    except Exception:
        return ""


def _versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for mod in ("ragas", "deepeval", "streamlit", "pandas", "plotly"):
        try:
            out[mod] = __import__("importlib.metadata", fromlist=["version"]).version(mod)
        except Exception:
            out[mod] = "not installed"
    return out


class Stopwatch:
    def __init__(self) -> None:
        self.t: dict[str, float] = {}

    def run(self, name: str):
        sw = self

        class _Ctx:
            def __enter__(self_inner):
                self_inner.t0 = time.monotonic()

            def __exit__(self_inner, *a):
                sw.t[name] = round(time.monotonic() - self_inner.t0, 2)

        return _Ctx()


def run_pipeline(cfg: RunConfig, progress: Progress | None = None) -> dict[str, Any]:
    """Run the whole pipeline. Raises LiveUnavailable / JudgeUnavailable (before any work) when a requested mode or
    judge cannot honestly run. Returns the summary dict (also written to results/<run_id>/ when cfg.write)."""
    from evals import judge as judge_mod
    from evals import report as report_mod

    sw = Stopwatch()
    started = now_iso()
    run_id = cfg.run_id or new_run_id(cfg.mode)
    run_dir = Path(cfg.results_dir) / run_id
    resume_dir = Path(cfg.results_dir) / cfg.resume if cfg.resume else None
    notes: list[str] = []

    def prog(stage: str, done: int, total: int, msg: str = "") -> None:
        if progress:
            progress(stage, done, total, msg)
        if cfg.write:
            with open(run_dir / "progress.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.time(), "stage": stage, "done": done, "total": total, "message": msg}) + "\n")

    # honest refusal first: nothing runs if the requested mode / judge cannot run
    asyncio.run(preflight(cfg.mode))
    judge_status = judge_mod.status()
    judge_obj = None
    if cfg.judge == "nebius":
        judge_status = judge_mod.require_judge(check_reachable=True)
        judge_obj = judge_mod.NebiusJudge()
    elif cfg.judge != "none":
        raise ValueError(f"unknown judge {cfg.judge!r} (none|nebius)")

    if cfg.write:
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_dir / "run.json", {"run_id": run_id, "status": "running", "started": started,
                                         "config": {k: str(v) if isinstance(v, Path) else v for k, v in asdict(cfg).items()}})

    # 1. dataset
    with sw.run("dataset"):
        prog("dataset", 0, 1, "loading and validating the golden dataset")
        ds = load_dataset(cfg.dataset_path)
        cases = select_cases(ds, cfg.suite, cfg.case_ids)
        if not cases:
            raise ValueError("no cases selected")
        prog("dataset", 1, 1, f"{len(cases)} of {len(ds.cases)} cases, version {ds.dataset_version}")

    # 2. integrity
    integrity: dict[str, Any] = {"skipped": True}
    if cfg.integrity:
        from evals.integrity import run_integrity

        with sw.run("integrity"):
            done_i = 0

            def on_case(rep: Any) -> None:
                nonlocal done_i
                done_i += 1
                prog("integrity", done_i, len(cases), f"{rep.case_id}: {'ok' if rep.ok else 'FAIL'}")

            integrity = asyncio.run(run_integrity(ds, [c.id for c in cases], on_case))
            integrity.pop("reports", None) if integrity.get("ok") else None

    # 3. SUT
    with sw.run("sut"):
        traces = asyncio.run(_run_suts(cfg, cases, run_dir, resume_dir, lambda s, d, t, m: prog(s, d, t, m)))

    # 4. deterministic metrics
    per_trial: dict[str, list[list[MetricResult]]] = {}
    per_case: dict[str, dict[str, MetricResult]] = {}
    with sw.run("metrics"):
        for i, case in enumerate(cases):
            ts = traces[case.id]
            per_trial[case.id] = [evaluate_trace(case, t) for t in ts]
            per_case[case.id] = aggregate_trials(case, per_trial[case.id])
            prog("metrics", i + 1, len(cases), case.id)

    items = [(c, t) for c in cases for t in traces[c.id]]
    first_items = [(c, traces[c.id][0]) for c in cases if traces[c.id]]  # LLM stages grade one trial per case

    # 5. DeepEval
    deepeval_results: list[dict[str, Any]] = []
    deepeval_summary: list[dict[str, Any]] = []
    with sw.run("deepeval"):
        if cfg.deepeval:
            from evals import deepeval_suite as de

            prog("deepeval", 0, 1, "offline metrics" + (" + judge metrics" if judge_obj else " (judge metrics: needs_judge)"))
            res = de.run_offline(first_items)
            res += asyncio.run(de.run_llm(first_items, judge_obj, judge_reason=judge_status.get("reason", "")))
            deepeval_results = [r.to_dict() for r in res]
            deepeval_summary = de.summarize(res, {c.id: c for c in cases})
            prog("deepeval", 1, 1, f"{sum(1 for r in res if r.status == 'ran')} metric results")

    # 6. Ragas
    ragas_out: dict[str, Any] = {"ok": False, "skipped": True, "results": [], "table": [], "coverage": []}
    with sw.run("ragas"):
        if cfg.ragas:
            from evals import ragas_suite as rs

            prog("ragas", 0, 1, "offline metrics" + (" + judge metrics" if judge_obj else " (LLM metrics: needs_judge)"))
            llm = emb = None
            if judge_obj is not None:
                llm = judge_mod.ragas_llm()
                emb = judge_mod.ragas_embeddings()
            ragas_out = rs.run_ragas(first_items, llm=llm, embeddings=emb, judge_reason=judge_status.get("reason", ""))
            prog("ragas", 1, 1, f"{sum(1 for r in ragas_out.get('results', []) if r['status'] == 'ran')} metric results")

    # 7. aggregate
    with sw.run("aggregate"):
        agg = aggregate(cases, per_case, traces)
        case_outcomes = {c.id: int(per_case[c.id]["outcome_match"].score == 1.0)
                         for c in cases if per_case[c.id].get("outcome_match") and per_case[c.id]["outcome_match"].applicable}
        for c in cases:  # probes have no outcome_match: use stage_match
            if c.id not in case_outcomes and per_case[c.id].get("stage_match") and per_case[c.id]["stage_match"].applicable:
                case_outcomes[c.id] = int(per_case[c.id]["stage_match"].score == 1.0)
        summary: dict[str, Any] = {
            "run_id": run_id, "created": started, "mode": cfg.mode, "engine": cfg.engine, "suite": cfg.suite,
            "case_filter": list(cfg.case_ids), "n": cfg.n, "cases": len(cases), "trials": len(items),
            "dataset_version": ds.dataset_version, "dataset_hash": dataset_hash(cfg.dataset_path),
            "fake_banner": FAKE_BANNER if cfg.mode == "fake" else None,
            "judge": {"mode": cfg.judge, **judge_status}, **agg, "case_outcomes": case_outcomes,
            "integrity": {k: v for k, v in integrity.items() if k != "reports"},
            "deepeval": deepeval_summary, "ragas": {"table": ragas_out.get("table", []),
                                                    "coverage": ragas_out.get("coverage", []),
                                                    "meta": ragas_out.get("meta", {})},
            "timings_s": dict(sw.t),
        }

    # 8. gate
    with sw.run("gate"):
        thresholds = load_thresholds(cfg.thresholds_path)
        baseline, label = resolve_baseline(cfg.baseline, cfg.mode, Path(cfg.results_dir))
        summary["gate"] = evaluate_gate(summary, baseline, label, thresholds)
        if not integrity.get("skipped") and not integrity.get("ok", True):
            summary["gate"]["checks"].append({"kind": "integrity", "metric": "integrity", "scope": "dataset", "ok": False,
                                              "message": f"golden dataset integrity failed for {integrity.get('failed_cases')}"})
            summary["gate"]["passed"], summary["gate"]["failed"] = False, summary["gate"]["failed"] + 1
        prog("gate", 1, 1, "PASSED" if summary["gate"]["passed"] else f"FAILED ({summary['gate']['failed']} checks)")

    # 9. write
    case_rows = []
    for c in cases:
        row = {"case_id": c.id, "category": c.category, "difficulty": c.difficulty, "title": c.title,
               "trials": len(traces[c.id]), "status": traces[c.id][0].status if traces[c.id] else "missing",
               "final_stage": traces[c.id][0].final_stage if traces[c.id] else "",
               "solved": traces[c.id][0].solved if traces[c.id] else False,
               "metrics": {n: r.to_dict() for n, r in per_case[c.id].items()},
               "deepeval": [r for r in deepeval_results if r["case_id"] == c.id],
               "ragas": [r for r in ragas_out.get("results", []) if r["case_id"] == c.id]}
        case_rows.append(row)
    summary["timings_s"] = dict(sw.t)
    with sw.run("report"):
        if cfg.write:
            run_dir.mkdir(parents=True, exist_ok=True)
            with open(run_dir / "cases.jsonl", "w", encoding="utf-8") as fh:
                for row in case_rows:
                    fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            write_json(run_dir / "summary.json", summary)
            write_json(run_dir / "run.json", {
                "run_id": run_id, "status": "completed", "started": started, "finished": now_iso(),
                "config": {k: str(v) if isinstance(v, Path) else v for k, v in asdict(cfg).items()},
                "git_sha": _git_sha(), "versions": _versions(), "eval_version": __version__,
                "compat": ragas_out.get("meta", {}).get("compat_stubbed", []), "judge": summary["judge"],
                "timings_s": dict(sw.t), "gate_passed": summary["gate"]["passed"], "notes": notes,
                "env": {"NEBIUS_API_KEY": "set" if os.environ.get("NEBIUS_API_KEY") else "unset",
                        "EVAL_JUDGE_MODEL": os.environ.get("EVAL_JUDGE_MODEL", "") or "unset"}})
            (run_dir / "report.md").write_text(report_mod.render_markdown(summary, case_rows), encoding="utf-8")
            (run_dir / "report.html").write_text(report_mod.render_html(summary, case_rows), encoding="utf-8")
            update_index(Path(cfg.results_dir), summary)
            if cfg.update_baseline:
                BASELINES_DIR.mkdir(parents=True, exist_ok=True)
                path = BASELINES_DIR / f"{cfg.mode}-baseline.json"
                write_json(path, baseline_from_summary(summary))
                notes.append(f"baseline written to {path}")
    summary["_run_dir"] = str(run_dir)
    summary["_cases"] = case_rows
    return summary


def update_index(results_dir: Path, summary: dict[str, Any]) -> None:
    path = Path(results_dir) / "index.json"
    idx = [r for r in (read_json(path, []) or []) if r.get("run_id") != summary["run_id"]]
    h = summary["headline"]
    idx.insert(0, {"run_id": summary["run_id"], "created": summary["created"], "mode": summary["mode"],
                   "engine": summary["engine"], "suite": summary["suite"], "cases": summary["cases"], "n": summary["n"],
                   "solve_rate": h.get("solve_rate"), "guard_tpr": h.get("guard_tpr"), "guard_fpr": h.get("guard_fpr"),
                   "honest_failure_rate": h.get("honest_failure_rate"), "latency_p95_ms": h.get("latency_p95_ms"),
                   "gate_passed": summary["gate"]["passed"], "judge": summary["judge"].get("mode", "none"),
                   "dataset_version": summary["dataset_version"]})
    write_json(path, idx[:200])


def list_runs(results_dir: Path = RESULTS_DIR) -> list[dict[str, Any]]:
    return read_json(Path(results_dir) / "index.json", []) or []


def load_run(run_id: str, results_dir: Path = RESULTS_DIR) -> dict[str, Any] | None:
    d = Path(results_dir) / run_id
    summary = read_json(d / "summary.json")
    if not summary:
        return None
    cases = []
    try:
        cases = [json.loads(line) for line in (d / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        pass
    return {"summary": summary, "cases": cases, "run": read_json(d / "run.json", {}), "dir": d}


def load_traces(run_id: str, results_dir: Path = RESULTS_DIR) -> dict[str, list[Trace]]:
    out: dict[str, list[Trace]] = {}
    for p in sorted((Path(results_dir) / run_id / "traces").glob("*.json")):
        data = read_json(p)
        if data:
            out.setdefault(data["case_id"], []).append(Trace.from_dict(data))
    return out
