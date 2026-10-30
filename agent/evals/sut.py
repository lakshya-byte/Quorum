"""System-under-test adapter: runs ONE golden case through the real PatchLoop code and returns a normalized Trace.

Paths (all real application code, no re-implementation of decisions):
  * bundled bug  + bug_fix / safety / unsolvable  -> RunRegistry.start()  (graph or loop engine) or the single-shot baseline
  * demo repo    + bug_fix / pr / followup / unsolvable -> RunRegistry.start_repo()  (guard, locate, repro, graph engine, PR)
  * locator_retrieval   -> team.locate() exactly as repo_flow calls it (no scripted hint: see README)
  * reproducer_quality  -> team.write_repro() + repo_flow.validate_reproducer() + sandbox runs
  * safety patch probes -> guard.check() + repo_eval.evaluate_repo_candidate() (policy gate -> tests -> bandit)

Modes: fake (scripted team, local sandbox), hybrid (real Nemotron, local sandbox), live (real Nemotron + Nebius
Sandboxes). hybrid/live REFUSE (LiveUnavailable) when credentials or the network are missing; they never fall back to
fake numbers.
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from evals.common import NEBIUS_BASE_URL
from evals.dataset import Case

EVENT_TEXT_CAP = 1500
DIFF_CAP = 6000
TOLERATED_TOOLS = ("critic",)  # present only when round 1 does not already solve: never required


class LiveUnavailable(RuntimeError):
    """hybrid/live was requested but cannot run here (missing keys or unreachable endpoint)."""


# ---- trace ------------------------------------------------------------------------------------

@dataclass
class Trace:
    case_id: str
    trial: int = 0
    mode: str = "fake"
    engine: str = "graph"
    kind: str = ""  # graph | loop | single | repo | probe_locator | probe_repro | probe_patch
    status: str = "ok"  # ok | error | timeout
    error: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    retrieved_files: list[str] = field(default_factory=list)
    retrieved_contents: dict[str, str] = field(default_factory=dict)
    repro: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    best_id: int | None = None
    guard: dict[str, Any] = field(default_factory=dict)
    policy_verdict: str = "n/a"
    security_verdict: str = "n/a"
    final: dict[str, Any] = field(default_factory=dict)
    solved: bool = False
    stopped: str = ""
    final_stage: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    ttfe_ms: int | None = None
    wall_ms: int = 0
    evidence: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Trace":
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    @property
    def best(self) -> dict[str, Any] | None:
        return next((c for c in self.candidates if c["id"] == self.best_id), None) if self.best_id is not None else None

    @property
    def baseline(self) -> dict[str, Any] | None:
        return next((c for c in self.candidates if c.get("baseline")), None)

    @property
    def tool_names(self) -> list[str]:
        return [t["name"] for t in self.tool_calls]

    @property
    def final_text(self) -> str:
        f = self.final or {}
        return (f"{f.get('title', '')}\n\n{f.get('body', '')}".strip()) if f else ""


# ---- settings, guard, readiness ----------------------------------------------------------------

def make_settings(mode: str, *, fake_delay_scale: float = 0.05, runs_dir: Any = None) -> Any:
    from app.config import load_settings

    s = load_settings()
    kw: dict[str, Any] = {"mode": mode, "fake_delay_scale": fake_delay_scale if mode == "fake" else 1.0}
    if runs_dir is not None:
        kw["runs_dir"] = runs_dir
    if mode == "fake":  # never let a stray .env point a fake run at a real backend
        kw.update(backend_callback_url="", github_token="", langsmith_api_key="")
    return dataclasses.replace(s, **kw)


async def _reachable(url: str, key: str) -> str | None:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"})
        return None if resp.status_code < 500 else f"HTTP {resp.status_code}"
    except Exception as exc:
        return type(exc).__name__


async def preflight(mode: str) -> dict[str, Any]:
    """Raise LiveUnavailable unless `mode` can really run here. fake always can."""
    if mode == "fake":
        return {"mode": "fake", "ready": True, "note": "scripted agents; validates the harness, not model quality"}
    s = make_settings(mode)
    if not s.llm_ready:
        raise LiveUnavailable(f"--mode {mode}: not verifiable here: set NEBIUS_API_KEY and MODEL_NANO")
    if mode == "live" and not s.sandbox_ready:
        raise LiveUnavailable("--mode live: set NEBIUS_PROJECT_ID (Nebius Sandboxes) or use --mode hybrid")
    err = await _reachable(NEBIUS_BASE_URL, s.nebius_api_key)
    if err:
        raise LiveUnavailable(f"--mode {mode}: not verifiable here: api.tokenfactory.nebius.com unreachable ({err})")
    return {"mode": mode, "ready": True, "models": {"nano": s.model_nano, "super": s.model_super or s.model_nano}}


class SutContext:
    """Per-pipeline-run shared state: settings, guard (probed once), sandbox concurrency."""

    def __init__(self, mode: str = "fake", engine: str = "graph", *, fake_delay_scale: float = 0.05,
                 runs_dir: Any = None) -> None:
        from app.guard import GuardService

        self.mode, self.engine = mode, engine
        self.settings = make_settings(mode, fake_delay_scale=fake_delay_scale, runs_dir=runs_dir)
        self.guard = GuardService(self.settings)
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if not self._started:
                await self.guard.startup()
                self._started = True


# ---- scripted fake team variants (fake mode only) ------------------------------------------------

def scripted_team(base: Any, script: str) -> Any:
    """Wrap the FakeTeam for dataset scripts. Only fake mode is ever wrapped; live teams are never altered."""
    if script == "default" or getattr(base, "kind", "") != "fake":
        return base

    class ScriptedFakeTeam(type(base)):  # type: ignore[misc]
        async def write_repro(self, bug, path, feedback, config, run_id=""):
            if script == "no_reproducer":
                return "", {"prompt_tokens": 350, "completion_tokens": 20}
            return await super().write_repro(bug, path, feedback, config, run_id)

        async def locate(self, task, files, config, run_id="", hint=None):
            return await super().locate(task, files, config, run_id, hint=None if script == "no_locator_hint" else hint)

    team = ScriptedFakeTeam(base.k)
    return team


def make_registry(ctx: SutContext, script: str, runs_dir: Any) -> Any:
    from app.runs import RunRegistry

    mode = ctx.mode

    class EvalRegistry(RunRegistry):
        def resolve_mode(self) -> str:  # never downgrade to fake behind the caller's back
            return mode

        def team(self, m: str, model_override: str | None = None) -> Any:
            return scripted_team(super().team(m, model_override), script)

        def save(self, run: Any) -> None:  # eval runs are not part of the product's run history
            return None

    settings = dataclasses.replace(ctx.settings, runs_dir=runs_dir) if runs_dir else ctx.settings
    return EvalRegistry(settings, ctx.guard)


# ---- helpers ------------------------------------------------------------------------------------

def _clip(text: Any, n: int) -> Any:
    return text[:n] + f"... [{len(text) - n} more chars]" if isinstance(text, str) and len(text) > n else text


def _slim_event(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    if kind == "node":
        keep = ("id", "parent", "depth", "idea", "strategy", "passed", "total", "score", "model", "latency_ms",
                "tokens", "policy", "security", "baseline")
        out = {k: data[k] for k in keep if k in data}
        out["files"] = sorted((data.get("files") or {}).keys())
        out["output_tail"] = _clip((data.get("output") or "")[-EVENT_TEXT_CAP:], EVENT_TEXT_CAP)
        return out
    if kind == "done":
        best = data.get("best") or {}
        slim = {k: v for k, v in data.items() if k != "best"}
        slim["best_id"] = best.get("id")
        return slim
    return {k: _clip(v, EVENT_TEXT_CAP) if isinstance(v, str) else v for k, v in data.items()}


class _Recorder:
    """Wraps run.emit so every event gets a millisecond offset."""

    def __init__(self, run: Any) -> None:
        self.t0 = time.monotonic()
        self.log: list[dict[str, Any]] = []
        self.raw_nodes: dict[int, dict[str, Any]] = {}
        self.done: dict[str, Any] = {}
        self._orig = run.emit
        run.emit = self.emit  # type: ignore[method-assign]

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        self.log.append({"t_ms": int((time.monotonic() - self.t0) * 1000), "type": kind, "data": _slim_event(kind, data)})
        if kind == "node":
            self.raw_nodes[data["id"]] = data
        if kind == "done":
            self.done = data
        self._orig(kind, data)


def _candidate(node: dict[str, Any], originals: dict[str, str], bug: dict[str, Any] | None) -> dict[str, Any]:
    from app.scoring import changed_lines

    files = dict(node.get("files") or {})
    if not files and bug is not None and not bug.get("repo"):
        if node.get("code") and node["code"] != bug["buggy"]:
            files = {bug["target"]: node["code"]}
    lines = sum(changed_lines(originals.get(p, ""), t) for p, t in files.items())
    out = (node.get("output") or "")
    return {
        "id": node["id"], "parent": node.get("parent"), "depth": node.get("depth", 0), "idea": node.get("idea", ""),
        "baseline": bool(node.get("baseline")) or node["id"] == 0, "changed_files": sorted(files),
        "diff": _clip(node.get("diff") or "", DIFF_CAP), "lines_changed": lines,
        "passed": node.get("passed", 0), "total": node.get("total", 0), "score": node.get("score", 0.0),
        "policy": node.get("policy", {"ok": True, "reasons": []}),
        "security": node.get("security", {"ok": True, "new_findings": []}),
        "model": node.get("model", ""), "tokens": node.get("tokens", 0), "latency_ms": node.get("latency_ms", 0),
        "output_tail": out[-EVENT_TEXT_CAP:], "policy_blocked": out.startswith("POLICY_BLOCKED"),
        "no_code": out.startswith("NO_CODE"),
    }


def _tool_calls(events: list[dict[str, Any]], has_reviewer: bool) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def add(name: str, t: int, **args: Any) -> None:
        calls.append({"name": name, "t_ms": t, "args": args})

    for ev in events:
        k, d, t = ev["type"], ev["data"], ev["t_ms"]
        if k == "guard" and d.get("stage") == "input":
            add("input_guard", t, verdict=d.get("verdict"))
        elif k == "locate":
            add("locator", t, files=[f["path"] for f in d.get("files", [])])
        elif k == "repro":
            add("test_writer", t, path=d.get("path"), failed_on_original=d.get("failed_on_original"))
        elif k == "triage":
            add("triage", t)
        elif k == "node":
            if d.get("id") == 0:
                add("sandbox_test", t, role="baseline")
                continue
            add("proposer", t, node=d.get("id"))
            tail = d.get("output_tail", "")
            blocked_early = tail.startswith("POLICY_BLOCKED") or tail.startswith("NO_CODE")
            add("policy_gate", t, node=d.get("id"), ok=d.get("policy", {}).get("ok", True))
            if not blocked_early:
                add("sandbox_test", t, node=d.get("id"), passed=d.get("passed"), total=d.get("total"))
                sec = d.get("security", {})
                if sec.get("scanned") or not sec.get("ok", True):
                    add("security_scan", t, node=d.get("id"), ok=sec.get("ok", True))
        elif k == "critic":
            add("critic", t, node=d.get("node_id"))
        elif k == "guard" and d.get("stage") == "output":
            if has_reviewer:
                add("reviewer", t)
            add("output_guard", t, verdict=d.get("verdict"))
    return calls


def _usage(done: dict[str, Any]) -> dict[str, Any]:
    u = dict(done.get("usage") or {})
    u.setdefault("total_tokens", int(u.get("prompt_tokens", 0)) + int(u.get("completion_tokens", 0)))
    return u


def _stage_of(trace: Trace, errors: list[dict[str, Any]]) -> str:
    stages = {e.get("stage") for e in errors}
    if "input_guard" in stages:
        return "blocked_guard"
    if trace.stopped == "locate":
        return "stopped_locate"
    if trace.stopped == "no_signal":
        return "stopped_no_signal"
    if trace.stopped == "no_tests":
        return "stopped_no_tests"
    if trace.final.get("kind") == "pr" and trace.final.get("url"):
        return "pr_opened"
    if trace.solved:
        return "solved"
    if trace.stopped == "budget":
        return "unsolved_exhausted"
    return "unsolved_exhausted" if trace.candidates else "stopped_no_signal"


def _final_from_run(run: Any, done: dict[str, Any], errors: list[dict[str, Any]], trace: Trace) -> dict[str, Any]:
    pr_events = [e["data"] for e in trace.events if e["type"] == "pr"]
    if done.get("solved"):
        best = done.get("best") or {}
        draft = run.pr_draft if run.pr_draft and run.pr_draft.get("guard") == "pass" else None
        if getattr(run, "kind", "") == "repo":
            from app.repo_pr import repo_pr_body

            label = "an isolated Nebius Sandbox" if run.mode in ("live", "replay") else "an isolated local sandbox"
            shim = {"issue": run.task, "reproducer_path": run.repro_path}
            body = repo_pr_body(shim, best, cause=run.cause, draft=draft, label=label, run_url=run.run_url,
                                issue_ref=run.issue_ref, safety=done.get("safety"), include_untrusted=True)
            title = ((draft or {}).get("title") or f"fix: {run.task.strip().splitlines()[0][:100]}")[:200]
            pr = pr_events[-1] if pr_events else {}
            return {"kind": "pr" if pr else "draft", "title": title, "body": body, "risk": (draft or {}).get("risk", ""),
                    "url": pr.get("url", ""), "branch": pr.get("branch", ""), "number": pr.get("number"),
                    "updated": bool(pr.get("updated")), "fake": bool(pr.get("fake")),
                    "body_source": "repo_pr_body() with the same arguments as repo_flow.open_run_pr"}
        d = run.pr_draft or {}
        return {"kind": "draft" if d else "none", "title": d.get("title", ""), "body": d.get("body", ""),
                "risk": d.get("risk", ""), "url": "", "branch": "", "number": None, "updated": False, "fake": False,
                "body_source": "reviewer agent output (bundled bugs open no pull request)"}
    msgs = [e.get("message", "") for e in errors if e.get("message")]
    best = done.get("best") or {}
    note = (f"NOT SOLVED. Stopped: {' | '.join(msgs)}" if msgs else
            f"NOT SOLVED. No candidate passed every test and gate (best: {best.get('passed', 0)}/{best.get('total', 0)} tests).")
    return {"kind": "stop", "title": "", "body": note, "risk": "", "url": "", "branch": "", "number": None,
            "updated": False, "fake": False, "synthesized": not msgs,
            "body_source": "error events of the run" if msgs else "synthesized by the eval adapter from the done event"}


def _evidence(trace: Trace) -> str:
    best = trace.best or {}
    parts = []
    if best.get("diff"):
        parts.append("DIFF:\n" + best["diff"])
    if best.get("output_tail"):
        parts.append("TEST OUTPUT (tail):\n" + best["output_tail"])
    return "\n\n".join(parts)


def _finalize(trace: Trace, rec: _Recorder, run: Any, originals: dict[str, str], bug: dict[str, Any] | None,
              t_start: float) -> Trace:
    trace.events = rec.log
    trace.stages = list(dict.fromkeys(e["type"] for e in rec.log))
    done = rec.done or {}
    errors = [e["data"] for e in rec.log if e["type"] == "error"]
    trace.candidates = [_candidate(n, originals, bug) for n in rec.raw_nodes.values()]
    best = done.get("best") or {}
    trace.best_id = best.get("id") if best else None
    trace.solved = bool(done.get("solved"))
    trace.stopped = done.get("stopped", "") or ""
    guards = [e["data"] for e in rec.log if e["type"] == "guard"]
    for g in guards:
        trace.guard[g.get("stage", "input")] = {"verdict": g.get("verdict"), "reasons": g.get("reasons", []),
                                                 "backend": g.get("backend", "")}
    locate = next((e["data"] for e in rec.log if e["type"] == "locate"), None)
    if locate:
        trace.retrieved_files = [f["path"] for f in locate.get("files", [])]
    repro = next((e["data"] for e in rec.log if e["type"] == "repro"), None)
    if repro:
        trace.repro = dict(repro)
    trace.usage = _usage(done)
    trace.latency_ms = int(done.get("latency_ms") or (time.monotonic() - t_start) * 1000)
    trace.ttfe_ms = done.get("time_to_first_event_ms")
    trace.wall_ms = int((time.monotonic() - t_start) * 1000)
    has_reviewer = bool(run.pr_draft) if run is not None else False
    trace.final = _final_from_run(run, done, errors, trace) if run is not None else trace.final
    trace.tool_calls = _tool_calls(rec.log, has_reviewer)
    trace.final_stage = _stage_of(trace, errors)
    trace.evidence = _evidence(trace)
    pol = [c for c in trace.candidates if not c["baseline"]]
    trace.policy_verdict = "block" if pol and any(not c["policy"]["ok"] for c in pol) else ("pass" if pol else "n/a")
    trace.security_verdict = "block" if any(not c["security"]["ok"] for c in pol) else (
        "pass" if any(c["security"].get("scanned") for c in pol) else "n/a")
    return trace


async def _wait(run: Any, registry: Any, timeout: float) -> bool:
    """Wait for a run to finish. True if it finished, False on timeout (the run is then abandoned)."""
    deadline = time.monotonic() + timeout
    while not run.finished:
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.01)
    if registry._tasks:
        await asyncio.wait(set(registry._tasks), timeout=10)
    return True


# ---- bundled bug path ---------------------------------------------------------------------------

def _bug_for_case(case: Case) -> dict[str, Any]:
    from app.bugs import BUGS

    bug = copy.deepcopy(BUGS[case.input.repo])
    bug["issue"] = case.input.full_text  # the agents and the guard see what the user wrote
    bug["id"] = case.input.repo
    return bug


async def _run_single(ctx: SutContext, bug: dict[str, Any], rec_log: list[dict[str, Any]]) -> dict[str, Any]:
    """Single-shot baseline (same logic as scripts/eval.py --engine single)."""
    from app.agents import DEFAULT_STRATEGIES
    from app.candidate import evaluate_candidate, is_solved
    from app.config import LOCAL_TEST_TIMEOUT
    from app.sandbox import LocalSandbox

    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
    team = make_registry(ctx, "default", None).team(ctx.mode)
    sandbox = LocalSandbox(LOCAL_TEST_TIMEOUT)
    guard = await ctx.guard.check("input", f"{bug['issue']}\n\n{bug['buggy']}", ctx.mode)
    rec_log.append({"t_ms": ms(), "type": "guard", "data": guard})
    if guard["verdict"] == "block":
        rec_log.append({"t_ms": ms(), "type": "error", "data": {"stage": "input_guard",
                        "message": "input blocked by guardrails: " + "; ".join(guard["reasons"])}})
        return {"solved": False, "best": None, "usage": {"prompt_tokens": 0, "completion_tokens": 0}, "latency_ms": ms()}
    root = await evaluate_candidate(bug, sandbox, node_id=0, parent=None, depth=0, idea="original buggy code",
                                    code=bug["buggy"], model="-", timeout=LOCAL_TEST_TIMEOUT, skip_policy=True)
    rec_log.append({"t_ms": ms(), "type": "node", "data": root})
    prop = await team.propose(bug, DEFAULT_STRATEGIES[0], {"id": 0, "depth": 0, "code": bug["buggy"], "output": ""},
                              "", "", 1, 0, None)
    node = await evaluate_candidate(bug, sandbox, node_id=1, parent=0, depth=1, idea=prop.idea, code=prop.code,
                                    model=prop.model, extra_files=prop.extra_files, timeout=LOCAL_TEST_TIMEOUT)
    rec_log.append({"t_ms": ms(), "type": "node", "data": node})
    used = dict(prop.usage)
    return {"solved": is_solved(node), "best": node, "usage": used, "latency_ms": ms(), "engine": "single"}


async def _run_bug_case(ctx: SutContext, case: Case, trial: int, timeout: float) -> Trace:
    import tempfile

    t_start = time.monotonic()
    bug = _bug_for_case(case)
    originals = {bug["target"]: bug["buggy"]}
    engine = ctx.engine
    trace = Trace(case.id, trial, ctx.mode, engine, kind="single" if engine == "single" else engine)
    if engine == "single":
        log: list[dict[str, Any]] = []
        done = await asyncio.wait_for(_run_single(ctx, bug, log), timeout)
        rec = _Recorder.__new__(_Recorder)
        rec.log, rec.raw_nodes, rec.done = [], {}, {}
        for e in log:
            kind, data = e["type"], e["data"]
            rec.log.append({"t_ms": e["t_ms"], "type": kind, "data": _slim_event(kind, data)})
            if kind == "node":
                rec.raw_nodes[data["id"]] = data
        done_ev = {**done, "usage": done.get("usage")}
        rec.done = done_ev
        rec.log.append({"t_ms": done["latency_ms"], "type": "done", "data": _slim_event("done", done_ev)})

        class _R:  # minimal run-like for _finalize
            pr_draft = None
            kind = "bug"
            mode = ctx.mode
        return _finalize(trace, rec, _R(), originals, bug, t_start)
    with tempfile.TemporaryDirectory(prefix="evals-runs-") as tmp:
        reg = make_registry(ctx, case.metadata.fake_script, tmp)
        run = reg.start(bug, mode=ctx.mode, engine=engine)
        rec = _Recorder(run)
        finished = await _wait(run, reg, timeout)
        if not finished:
            trace.status, trace.error = "timeout", f"run did not finish within {timeout}s"
        if run.mode != ctx.mode:
            raise RuntimeError(f"run executed in mode {run.mode!r}, expected {ctx.mode!r}")
        trace = _finalize(trace, rec, run, originals, bug, t_start)
    return trace


# ---- demo repo path ------------------------------------------------------------------------------

_DEMO: dict[str, Any] = {}


def demo_snapshot(name: str) -> Any:
    from app.repo_loader import load_demo

    if name not in _DEMO:
        _DEMO[name] = load_demo(name)
    return _DEMO[name]


def _repo_spec(case: Case, snap: Any) -> Any:
    from app.repo_flow import RepoSpec

    followup = None
    if case.input.followup:
        f = case.input.followup
        followup = {"message": f.message, "pr_branch": f.pr_branch, "pr_number": f.pr_number,
                    "previous_files": dict(snap.meta["fixes"]["correct"]), "pr_url":
                    f"https://github.com/demo/{snap.full_name.split('/', 1)[-1]}/pull/{f.pr_number}"}
    return RepoSpec(task=case.input.full_text, full_name=snap.full_name, branch="main", token="", auto_pr=True,
                    source=case.input.source, issue_ref=case.input.issue_ref, followup=followup)


async def _run_repo_case(ctx: SutContext, case: Case, trial: int, timeout: float) -> Trace:
    import tempfile

    t_start = time.monotonic()
    name = case.input.repo.split("/", 1)[1]
    snap = demo_snapshot(name)
    trace = Trace(case.id, trial, ctx.mode, "graph", kind="repo")
    with tempfile.TemporaryDirectory(prefix="evals-runs-") as tmp:
        reg = make_registry(ctx, case.metadata.fake_script, tmp)
        spec = _repo_spec(case, snap)
        run = reg.start_repo(spec)
        rec = _Recorder(run)
        finished = await _wait(run, reg, timeout)
        if not finished:
            trace.status, trace.error = "timeout", f"run did not finish within {timeout}s"
        if run.mode != ctx.mode:
            raise RuntimeError(f"run executed in mode {run.mode!r}, expected {ctx.mode!r}")
        trace = _finalize(trace, rec, run, dict(snap.files), None, t_start)
    if trace.retrieved_files:
        trace.retrieved_contents = {p: snap.files.get(p, "")[:4000] for p in trace.retrieved_files}
    trace.meta["followup"] = bool(case.input.followup)
    if case.input.followup:
        trace.meta["followup_expected"] = {"pr_branch": case.input.followup.pr_branch,
                                           "pr_number": case.input.followup.pr_number}
    return trace


# ---- probes --------------------------------------------------------------------------------------

async def _guard_event(ctx: SutContext, text: str) -> dict[str, Any]:
    return await ctx.guard.check("input", text, ctx.mode)


def _probe_trace(case: Case, trial: int, ctx: SutContext, kind: str) -> Trace:
    return Trace(case.id, trial, ctx.mode, "graph", kind=kind)


async def _run_locator_probe(ctx: SutContext, case: Case, trial: int, timeout: float) -> Trace:
    from app.repo_agents import heuristic_locate
    from app.repo_detect import is_test_path

    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
    name = case.input.repo.split("/", 1)[1]
    snap = demo_snapshot(name)
    tr = _probe_trace(case, trial, ctx, "probe_locator")
    reg = make_registry(ctx, "default", None)
    team = reg.team(ctx.mode)
    text = case.input.full_text
    g = await _guard_event(ctx, text)
    tr.events.append({"t_ms": ms(), "type": "guard", "data": g})
    tr.guard["input"] = {"verdict": g["verdict"], "reasons": g["reasons"], "backend": g["backend"]}
    tr.tool_calls.append({"name": "input_guard", "t_ms": ms(), "args": {"verdict": g["verdict"]}})
    # exactly what repo_flow does, except no scripted `hint` is passed (the keyword/LLM locator must find the files)
    located, used = await asyncio.wait_for(team.locate(text, snap.files, None, uuid.uuid4().hex, hint=None), timeout)
    located = [x for x in located if x["path"] in snap.files and not is_test_path(x["path"])] \
        or heuristic_locate(text, snap.files)
    tr.events.append({"t_ms": ms(), "type": "locate", "data": {"files": located}})
    tr.tool_calls.append({"name": "locator", "t_ms": ms(), "args": {"files": [x["path"] for x in located]}})
    tr.retrieved_files = [x["path"] for x in located]
    tr.retrieved_contents = {p: snap.files[p][:4000] for p in tr.retrieved_files}
    tr.usage = {"prompt_tokens": used.get("prompt_tokens", 0), "completion_tokens": used.get("completion_tokens", 0),
                "total_tokens": used.get("prompt_tokens", 0) + used.get("completion_tokens", 0), "cost_usd": None}
    tr.final = {"kind": "probe", "title": "", "body": "Located: " + ", ".join(
        f"{x['path']} ({x['reason']})" for x in located) if located else "No related file found.",
        "url": "", "branch": "", "number": None}
    tr.final_stage, tr.stages = "probe_complete", ["guard", "locate"]
    tr.latency_ms = tr.wall_ms = ms()
    tr.ttfe_ms = tr.events[0]["t_ms"]
    tr.meta["locator"] = "FakeTeam keyword heuristic (heuristic_locate)" if ctx.mode == "fake" else "LiveTeam LLM locator"
    return tr


async def _run_repro_probe(ctx: SutContext, case: Case, trial: int, timeout: float) -> Trace:
    from app.repo_agents import first_test_name, repro_path_for
    from app.repo_eval import build_repo_bug, run_tests
    from app.repo_flow import REPO_TEST_TIMEOUT, validate_reproducer
    from app.sandbox import LocalSandbox, NebiusSandbox
    from app.scoring import parse_results

    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
    name = case.input.repo.split("/", 1)[1]
    snap = demo_snapshot(name)
    tr = _probe_trace(case, trial, ctx, "probe_repro")
    reg = make_registry(ctx, "default", None)
    team = reg.team(ctx.mode)
    sandbox = NebiusSandbox() if ctx.mode == "live" else LocalSandbox(REPO_TEST_TIMEOUT, 4)
    text = case.input.full_text
    g = await _guard_event(ctx, text)
    tr.events.append({"t_ms": ms(), "type": "guard", "data": g})
    tr.guard["input"] = {"verdict": g["verdict"], "reasons": g["reasons"], "backend": g["backend"]}
    tr.tool_calls.append({"name": "input_guard", "t_ms": ms(), "args": {"verdict": g["verdict"]}})
    located, _ = await asyncio.wait_for(team.locate(text, snap.files, None, uuid.uuid4().hex,
                                                    hint=snap.meta.get("locate")), timeout)
    tr.tool_calls.append({"name": "locator", "t_ms": ms(), "args": {"files": [x["path"] for x in located]}})
    tr.retrieved_files = [x["path"] for x in located]
    bug = build_repo_bug(snap, text, tr.retrieved_files, uuid.uuid4().hex)
    handle = await sandbox.checkpoint(snap.files)
    bug["checkpoint"] = handle
    path = repro_path_for(snap.files)
    bug["fake_repro"] = next(iter(snap.meta["repro_text"].values()), "")
    try:
        suite_code, suite_out = await run_tests(bug, sandbox, {}, REPO_TEST_TIMEOUT)
        sp, st = parse_results(suite_out, suite_code, snap.language)
        repro_text, used = await asyncio.wait_for(team.write_repro(bug, path, "", None, uuid.uuid4().hex), timeout)
        tr.tool_calls.append({"name": "test_writer", "t_ms": ms(), "args": {"path": path}})
        accepted, tail = (False, "no reproducer returned")
        passes_on_fix = False
        if repro_text:
            accepted, tail = await validate_reproducer(bug, sandbox, snap, path, repro_text, REPO_TEST_TIMEOUT)
            tr.tool_calls.append({"name": "sandbox_test", "t_ms": ms(), "args": {"role": "reproducer_on_original"}})
            bug["tests"], bug["reproducer_path"] = repro_text, path
            fix = dict(snap.meta["fixes"]["correct"])
            code, out = await run_tests(bug, sandbox, fix, REPO_TEST_TIMEOUT)
            fp, ft = parse_results(out, code, snap.language)
            passes_on_fix = ft > 0 and fp == ft
            tr.tool_calls.append({"name": "sandbox_test", "t_ms": ms(), "args": {"role": "reproducer_on_reference_fix"}})
    finally:
        await sandbox.release(handle)
    tr.repro = {"path": path, "test_name": first_test_name(repro_text or ""), "failed_on_original": accepted,
                "passes_on_reference_fix": passes_on_fix, "output_tail": tail[-800:],
                "existing_suite_on_original": {"passed": sp, "total": st}}
    tr.events.append({"t_ms": ms(), "type": "repro", "data": tr.repro})
    tr.usage = {"prompt_tokens": used.get("prompt_tokens", 0), "completion_tokens": used.get("completion_tokens", 0),
                "total_tokens": used.get("prompt_tokens", 0) + used.get("completion_tokens", 0), "cost_usd": None}
    tr.final = {"kind": "probe", "title": "", "url": "", "branch": "", "number": None,
                "body": f"Reproducer {path}: failed_on_original={accepted}, passes_on_reference_fix={passes_on_fix}. "
                        f"Existing suite on the original: {sp}/{st} pass.\n\n{(repro_text or '')[:1500]}"}
    tr.final_stage, tr.stages = "probe_complete", ["guard", "locate", "repro"]
    tr.latency_ms = tr.wall_ms = ms()
    tr.ttfe_ms = tr.events[0]["t_ms"]
    tr.evidence = tail[-800:]
    return tr


async def _run_patch_probe(ctx: SutContext, case: Case, trial: int, timeout: float) -> Trace:
    from app.repo_eval import build_repo_bug, evaluate_repo_candidate
    from app.repo_flow import REPO_TEST_TIMEOUT
    from app.sandbox import LocalSandbox, NebiusSandbox

    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731
    name = case.input.repo.split("/", 1)[1]
    snap = demo_snapshot(name)
    tr = _probe_trace(case, trial, ctx, "probe_patch")
    g = await _guard_event(ctx, case.input.full_text)
    tr.events.append({"t_ms": ms(), "type": "guard", "data": g})
    tr.guard["input"] = {"verdict": g["verdict"], "reasons": g["reasons"], "backend": g["backend"]}
    tr.tool_calls.append({"name": "input_guard", "t_ms": ms(), "args": {"verdict": g["verdict"]}})
    sandbox = NebiusSandbox() if ctx.mode == "live" else LocalSandbox(REPO_TEST_TIMEOUT, 4)
    bug = build_repo_bug(snap, case.input.full_text, [x["path"] for x in snap.meta["locate"]], uuid.uuid4().hex,
                         snap.meta.get("repro_path", "tests/test_patchloop_repro.py"),
                         next(iter(snap.meta["repro_text"].values()), ""))
    handle = await sandbox.checkpoint(snap.files)
    bug["checkpoint"] = handle
    try:
        node = await asyncio.wait_for(evaluate_repo_candidate(
            bug, sandbox, node_id=1, parent=0, depth=1, idea="[eval] adversarial patch", files=dict(case.input.adversarial_patch or {}),
            model="-", timeout=REPO_TEST_TIMEOUT, max_diff_lines=ctx.settings.max_diff_lines), timeout)
    finally:
        await sandbox.release(handle)
    node["output"] = node.get("output", "")
    tr.events.append({"t_ms": ms(), "type": "node", "data": _slim_event("node", node)})
    cand = _candidate(node, dict(snap.files), None)
    cand["changed_files"] = sorted((case.input.adversarial_patch or {}))
    tr.candidates = [cand]
    tr.tool_calls.append({"name": "policy_gate", "t_ms": ms(), "args": {"ok": node["policy"]["ok"]}})
    if node["policy"]["ok"]:
        tr.tool_calls.append({"name": "sandbox_test", "t_ms": ms(), "args": {"passed": node["passed"], "total": node["total"]}})
        tr.tool_calls.append({"name": "security_scan", "t_ms": ms(), "args": {"ok": node["security"]["ok"]}})
    tr.policy_verdict = "pass" if node["policy"]["ok"] else "block"
    tr.security_verdict = ("pass" if node["security"]["ok"] else "block") if node["policy"]["ok"] else "n/a"
    tr.final_stage = ("policy_blocked" if not node["policy"]["ok"] else
                      "security_blocked" if not node["security"]["ok"] else "probe_complete")
    tr.solved = False
    reasons = node["policy"]["reasons"] or [f["text"] for f in node["security"].get("new_findings", [])]
    tr.final = {"kind": "stop" if tr.final_stage != "probe_complete" else "probe", "title": "", "url": "",
                "branch": "", "number": None,
                "body": ("Candidate rejected: " + "; ".join(reasons)) if reasons else "Candidate accepted by every gate."}
    tr.stages = ["guard", "node"]
    tr.latency_ms = tr.wall_ms = ms()
    tr.ttfe_ms = tr.events[0]["t_ms"]
    tr.evidence = node.get("output", "")[-800:]
    return tr


# ---- public entry point ---------------------------------------------------------------------------

async def run_case(ctx: SutContext, case: Case, trial: int = 0, timeout: float = 120.0) -> Trace:
    """Run one case once. Never raises for case-level failures: they come back as Trace.status == 'error'."""
    await ctx.start()
    t0 = time.monotonic()
    try:
        if case.category == "locator_retrieval":
            tr = await _run_locator_probe(ctx, case, trial, timeout)
        elif case.category == "reproducer_quality":
            tr = await _run_repro_probe(ctx, case, trial, timeout)
        elif case.input.adversarial_patch:
            tr = await _run_patch_probe(ctx, case, trial, timeout)
        elif "/" in case.input.repo:
            tr = await _run_repo_case(ctx, case, trial, timeout)
        else:
            tr = await _run_bug_case(ctx, case, trial, timeout)
    except asyncio.TimeoutError:
        tr = Trace(case.id, trial, ctx.mode, ctx.engine, status="timeout", error=f"timeout after {timeout}s")
    except LiveUnavailable:
        raise
    except Exception as exc:
        tr = Trace(case.id, trial, ctx.mode, ctx.engine, status="error", error=f"{type(exc).__name__}: {exc}")
    tr.wall_ms = tr.wall_ms or int((time.monotonic() - t0) * 1000)
    tr.mode, tr.trial = ctx.mode, trial
    return tr
