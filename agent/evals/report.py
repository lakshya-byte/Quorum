"""Markdown and HTML reports for a run. Pure functions of (summary, case_rows)."""
from __future__ import annotations

import html
from typing import Any

from evals.common import FAKE_BANNER

CAT_SHORT = {"bug_fix_single_file": "single", "bug_fix_multi_file": "multi", "locator_retrieval": "locator",
             "reproducer_quality": "repro", "safety_guardrails": "safety", "unsolvable_or_underspecified": "unsolv",
             "followup_change_request": "follow", "pr_quality": "pr"}
HIDE = {"latency_ms", "total_tokens", "ttfe_ms", "cost_usd"}


def fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return f"{v:.{nd}f}" if isinstance(v, float) and abs(v) < 1000 else f"{v:,.0f}"
    return str(v)


def pivot(summary: dict[str, Any], include_perf: bool = False) -> tuple[list[str], list[list[str]]]:
    """(header, rows): metric x (overall + categories)."""
    cats = [c for c in CAT_SHORT if c in summary["by_category"]]
    header = ["metric", "n", "overall", *[CAT_SHORT[c] for c in cats]]
    rows = []
    for name in summary["metric_names"]:
        if name in HIDE and not include_perf:
            continue
        o = summary["overall"].get(name, {})
        if not o.get("n"):
            continue
        row = [name, str(o["n"]), fmt(o.get("mean"))]
        for c in cats:
            g = summary["by_category"][c].get(name, {})
            row.append(fmt(g.get("mean")) if g.get("n") else "")
        rows.append(row)
    return header, rows


def difficulty_pivot(summary: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    diffs = [d for d in ("easy", "medium", "hard") if d in summary["by_difficulty"]]
    rows = []
    for name in ("solved", "outcome_match", "tests_passed_ratio", "patch_minimality", "files_f1", "tool_f1",
                 "guard_accuracy", "claim_supported"):
        vals = [summary["by_difficulty"][d].get(name, {}) for d in diffs]
        if any(v.get("n") for v in vals):
            rows.append([name, *[fmt(v.get("mean")) if v.get("n") else "" for v in vals]])
    return ["metric", *diffs], rows


def attention(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in case_rows:
        bad = [f"{n}={m['score']:.2f}" for n, m in r["metrics"].items()
               if m.get("passed") is False and n not in HIDE]
        if bad or r["status"] != "ok":
            out.append({"case_id": r["case_id"], "category": r["category"], "stage": r["final_stage"],
                        "failed": bad, "status": r["status"]})
    return out


def skipped_explanation(summary: dict[str, Any]) -> list[str]:
    msgs = []
    for r in summary.get("deepeval", []):
        if r["status"] == "needs_judge":
            msgs.append(f"DeepEval {r['metric']}: needs a judge ({r['needs_judge']} case(s))")
    for r in summary.get("ragas", {}).get("table", []):
        if r["status"] in ("needs_judge", "needs_embeddings", "error"):
            msgs.append(f"Ragas {r['metric']}: {r['status']} - {r.get('skip_reason') or r['interpretation']}")
    return msgs


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_none_\n"
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def headline_rows(summary: dict[str, Any]) -> list[list[str]]:
    h = summary["headline"]
    return [
        ["solve rate (pass@1)", fmt(h.get("solve_rate")), f"{h.get('solves')}/{h.get('solve_trials')} fixable trials solved"],
        ["pass@k", fmt(h.get("pass_at_k")), "only when n > 1"],
        ["guard TPR (hostile blocked)", fmt(h.get("guard_tpr")), "input guard, expected-block cases"],
        ["guard FPR (benign blocked)", fmt(h.get("guard_fpr")), "input guard, expected-pass cases"],
        ["honest-failure rate", fmt(h.get("honest_failure_rate")), "unsolvable/hostile cases that stopped honestly"],
        ["latency p50 / p95", f"{fmt(h.get('latency_p50_ms'))} / {fmt(h.get('latency_p95_ms'))} ms", "end to end"],
        ["time to first event p50 / p95", f"{fmt(h.get('ttfe_p50_ms'))} / {fmt(h.get('ttfe_p95_ms'))} ms", ""],
        ["tokens total / per solve", f"{fmt(h.get('tokens_total'))} / {fmt(h.get('tokens_per_solve'))}", ""],
        ["cost per solve", fmt(h.get("cost_per_solve_usd")) if h.get("cost_per_solve_usd") is not None else "n/a",
         "needs PRICE_IN_PER_MTOK / PRICE_OUT_PER_MTOK"],
    ]


def render_markdown(summary: dict[str, Any], case_rows: list[dict[str, Any]]) -> str:
    s = summary
    out = [f"# PatchLoop eval report: {s['run_id']}\n"]
    if s.get("fake_banner"):
        out.append(f"> **FAKE MODE**: scripted agents: validates the harness, not model quality.\n> {FAKE_BANNER}\n")
    out.append(_md_table(["field", "value"], [
        ["mode / engine", f"{s['mode']} / {s['engine']}"], ["suite", f"{s['suite']} ({s['cases']} cases, {s['trials']} trials, n={s['n']})"],
        ["dataset", f"v{s['dataset_version']} ({s['dataset_hash']})"], ["created", s["created"]],
        ["judge", f"{s['judge'].get('mode')} - {s['judge'].get('reason')}"],
        ["integrity", "skipped" if s["integrity"].get("skipped") else
         f"{'PASSED' if s['integrity'].get('ok') else 'FAILED'} ({s['integrity'].get('checks')} checks)"],
        ["timings (s)", ", ".join(f"{k} {v}" for k, v in s["timings_s"].items())]]))
    g = s["gate"]
    out.append(f"\n## Gate: {'PASSED' if g['passed'] else 'FAILED'}\n\nBaseline: {g['baseline']}\n")
    out.append(_md_table(["", "check", "detail"], [["ok" if c["ok"] else "FAIL", f"{c['kind']}: {c['metric']}", c["message"]]
                                                   for c in g["checks"]]))
    out.append("\n## Headline\n")
    out.append(_md_table(["measure", "value", "note"], headline_rows(s)))
    h, rows = pivot(s)
    out.append("\n## Metrics by category (mean score over applicable cases)\n")
    out.append(_md_table(h, rows))
    h, rows = difficulty_pivot(s)
    out.append("\n## Metrics by difficulty\n")
    out.append(_md_table(h, rows))
    att = attention(case_rows)
    out.append("\n## Cases needing attention\n")
    out.append(_md_table(["case", "category", "stage", "failed metrics"], [[a["case_id"], a["category"], a["stage"],
                                                                         ", ".join(a["failed"]) or a["status"]] for a in att]))
    out.append("\n## DeepEval\n")
    out.append(_md_table(["metric", "kind", "status", "n ran", "mean", "pass rate"], [
        [r["metric"], r["kind"], r["status"], str(r["ran"]), fmt(r["mean"]), fmt(r["pass_rate"])] for r in s["deepeval"]]))
    rg = s["ragas"]
    out.append("\n## Ragas analysis\n")
    out.append(_md_table(["metric", "family", "what it measures for PatchLoop", "status", "n", "mean", "min", "interpretation"], [
        [r["metric"], r["family"], r["what"], r["status"], str(r["n"]), fmt(r["mean"]), fmt(r["min"]), r["interpretation"]]
        for r in rg.get("table", [])]))
    out.append("\n### Ragas metric coverage matrix\n")
    out.append(_md_table(["family", "ragas metric", "applies to PatchLoop", "this run", "how / why not"], [
        [c["family"], c["metric"], c["applies"], c["status"], c["how"]] for c in rg.get("coverage", [])]))
    sk = skipped_explanation(s)
    out.append("\n## Skipped metrics\n")
    out.append("\n".join(f"- {m}" for m in sk) + "\n" if sk else "_none_\n")
    out.append("\n## Per case\n")
    out.append(_md_table(["case", "category", "diff", "stage", "solved", "failed metrics"], [
        [r["case_id"], CAT_SHORT.get(r["category"], r["category"]), r["difficulty"], r["final_stage"],
         "yes" if r["solved"] else "no", ", ".join(f"{n}" for n, m in r["metrics"].items() if m.get("passed") is False) or "-"]
        for r in case_rows]))
    if s.get("fake_banner"):
        out.append(f"\n---\n{FAKE_BANNER}\n")
    return "\n".join(out)


CSS = """body{font:14px/1.5 system-ui,sans-serif;margin:24px auto;max-width:1180px;padding:0 16px;color:#1b1f24;background:#fff}
h1{font-size:22px}h2{font-size:17px;margin-top:28px;border-bottom:1px solid #d8dee4;padding-bottom:4px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}th,td{border:1px solid #d8dee4;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#f6f8fa}.banner{background:#fff4ce;border:1px solid #d4a72c;padding:10px 14px;border-radius:6px;margin:12px 0}
.ok{color:#1a7f37;font-weight:600}.fail{color:#cf222e;font-weight:600}.skip{color:#6e7781}
.bar{display:inline-block;height:8px;background:#2f81f7;border-radius:4px;vertical-align:middle}
@media (prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}th{background:#161b22}th,td{border-color:#30363d}
h2{border-color:#30363d}.banner{background:#3d2f00;border-color:#9e6a03}}"""


def _html_table(header: list[str], rows: list[list[str]], status_col: int | None = None) -> str:
    if not rows:
        return "<p class='skip'>none</p>"
    head = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    body = []
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            cls = ""
            if status_col is not None and i == status_col:
                cls = " class='ok'" if c in ("ok", "ran", "yes") else (" class='fail'" if c in ("FAIL", "error") else " class='skip'")
            cells.append(f"<td{cls}>{html.escape(str(c))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_html(summary: dict[str, Any], case_rows: list[dict[str, Any]]) -> str:
    s, g = summary, summary["gate"]
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>PatchLoop eval {html.escape(s['run_id'])}</title><style>{CSS}</style></head><body>",
             f"<h1>PatchLoop eval report: {html.escape(s['run_id'])}</h1>"]
    if s.get("fake_banner"):
        parts.append(f"<div class='banner'><b>FAKE MODE</b>: scripted agents: validates the harness, not model quality.<br>"
                     f"{html.escape(FAKE_BANNER)}</div>")
    parts.append(_html_table(["field", "value"], [
        ["mode / engine", f"{s['mode']} / {s['engine']}"], ["suite", f"{s['suite']} ({s['cases']} cases, {s['trials']} trials, n={s['n']})"],
        ["dataset", f"v{s['dataset_version']} ({s['dataset_hash']})"], ["created", s["created"]],
        ["judge", f"{s['judge'].get('mode')} - {s['judge'].get('reason')}"]]))
    parts.append(f"<h2>Gate: <span class='{'ok' if g['passed'] else 'fail'}'>{'PASSED' if g['passed'] else 'FAILED'}</span></h2>"
                 f"<p>Baseline: {html.escape(str(g['baseline']))}</p>")
    parts.append(_html_table(["", "check", "detail"], [["ok" if c["ok"] else "FAIL", f"{c['kind']}: {c['metric']}", c["message"]]
                                                       for c in g["checks"]], 0))
    parts.append("<h2>Headline</h2>" + _html_table(["measure", "value", "note"], headline_rows(s)))
    h, rows = pivot(s)
    parts.append("<h2>Metrics by category</h2>" + _html_table(h, rows))
    h, rows = difficulty_pivot(s)
    parts.append("<h2>Metrics by difficulty</h2>" + _html_table(h, rows))
    att = attention(case_rows)
    parts.append("<h2>Cases needing attention</h2>" + _html_table(["case", "category", "stage", "failed metrics"], [
        [a["case_id"], a["category"], a["stage"], ", ".join(a["failed"]) or a["status"]] for a in att]))
    parts.append("<h2>DeepEval</h2>" + _html_table(["metric", "kind", "status", "n ran", "mean", "pass rate"], [
        [r["metric"], r["kind"], r["status"], str(r["ran"]), fmt(r["mean"]), fmt(r["pass_rate"])] for r in s["deepeval"]], 2))
    rg = s["ragas"]
    parts.append("<h2>Ragas analysis</h2>" + _html_table(["metric", "family", "what it measures for PatchLoop", "status", "n", "mean", "min", "interpretation"], [
        [r["metric"], r["family"], r["what"], r["status"], str(r["n"]), fmt(r["mean"]), fmt(r["min"]), r["interpretation"]]
        for r in rg.get("table", [])], 3))
    parts.append("<h3>Ragas metric coverage matrix</h3>" + _html_table(["family", "ragas metric", "applies", "this run", "how / why not"], [
        [c["family"], c["metric"], c["applies"], c["status"], c["how"]] for c in rg.get("coverage", [])], 3))
    sk = skipped_explanation(s)
    parts.append("<h2>Skipped metrics</h2>" + ("<ul>" + "".join(f"<li>{html.escape(m)}</li>" for m in sk) + "</ul>" if sk else "<p class='skip'>none</p>"))
    parts.append("<h2>Per case</h2>" + _html_table(["case", "category", "diff", "stage", "solved", "failed metrics"], [
        [r["case_id"], CAT_SHORT.get(r["category"], r["category"]), r["difficulty"], r["final_stage"], "yes" if r["solved"] else "no",
         ", ".join(n for n, m in r["metrics"].items() if m.get("passed") is False) or "-"] for r in case_rows], 4))
    if s.get("fake_banner"):
        parts.append(f"<div class='banner'>{html.escape(FAKE_BANNER)}</div>")
    parts.append("</body></html>")
    return "".join(parts)
