"""Plotly figures for the Streamlit pages. Pure functions of summary dicts (no Streamlit calls)."""
from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

C = {"blue": "#2f81f7", "green": "#2da44e", "red": "#cf222e", "amber": "#bf8700", "grey": "#8c959f", "purple": "#8250df"}
CATS = ["#2f81f7", "#2da44e", "#8250df", "#bf8700", "#cf222e", "#1b7c83", "#d1672b", "#6e7781"]
SHORT = {"bug_fix_single_file": "single", "bug_fix_multi_file": "multi", "locator_retrieval": "locator",
         "reproducer_quality": "repro", "safety_guardrails": "safety", "unsolvable_or_underspecified": "unsolv",
         "followup_change_request": "follow-up", "pr_quality": "pr"}
LAYOUT = dict(margin=dict(l=10, r=10, t=78, b=10), height=380,
              legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0))


def _base(fig: go.Figure, title: str, height: int | None = None) -> go.Figure:
    fig.update_layout(title=dict(text=title, font=dict(size=15), y=0.97, yanchor="top"), **{**LAYOUT, **({"height": height} if height else {})})
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


def trend(index: list[dict[str, Any]]) -> go.Figure:
    runs = list(reversed(index))[-30:]
    x = [r["run_id"][4:15] for r in runs]
    fig = go.Figure()
    for key, label, color in (("solve_rate", "solve rate", C["blue"]), ("guard_tpr", "guard TPR", C["green"]),
                              ("honest_failure_rate", "honest failure", C["purple"])):
        fig.add_trace(go.Scatter(x=x, y=[r.get(key) for r in runs], mode="lines+markers", name=label,
                                 line=dict(color=color), connectgaps=False))
    bad = [i for i, r in enumerate(runs) if not r.get("gate_passed")]
    if bad:
        fig.add_trace(go.Scatter(x=[x[i] for i in bad], y=[1.04] * len(bad), mode="markers", name="gate failed",
                                 marker=dict(color=C["red"], symbol="x", size=11)))
    fig.update_yaxes(range=[0, 1.08], tickformat=".0%")
    return _base(fig, "Trend over runs")


def metric_bars(rows: list[dict[str, Any]], title: str = "Mean score by metric") -> go.Figure:
    rows = [r for r in rows if r.get("mean") is not None]
    rows.sort(key=lambda r: r["mean"])
    fig = go.Figure(go.Bar(x=[r["mean"] for r in rows], y=[r["metric"] for r in rows], orientation="h",
                           marker_color=[C["green"] if r["mean"] >= 0.8 else (C["amber"] if r["mean"] >= 0.5 else C["red"])
                                         for r in rows],
                           text=[f"{r['mean']:.2f}" for r in rows], textposition="outside"))
    fig.update_xaxes(range=[0, 1.12])
    return _base(fig, title, max(260, 24 * len(rows) + 80))


def category_bars(by_cat: dict[str, dict[str, Any]], metrics: list[str], title: str) -> go.Figure:
    fig = go.Figure()
    for i, m in enumerate(metrics):
        cats = [c for c in by_cat if by_cat[c].get(m, {}).get("n")]
        fig.add_trace(go.Bar(name=m, x=[SHORT.get(c, c) for c in cats],
                             y=[by_cat[c][m]["mean"] for c in cats], marker_color=CATS[i % len(CATS)]))
    fig.update_yaxes(range=[0, 1.05])
    fig.update_layout(barmode="group")
    return _base(fig, title)


def radar(by_cat: dict[str, dict[str, Any]], metric: str, title: str | None = None) -> go.Figure:
    cats = [c for c in by_cat if by_cat[c].get(metric, {}).get("n")]
    vals = [by_cat[c][metric]["mean"] for c in cats]
    fig = go.Figure()
    if cats:
        fig.add_trace(go.Scatterpolar(r=[*vals, vals[0]], theta=[*[c.replace("_", " ") for c in cats], cats[0].replace("_", " ")],
                                      fill="toself", name=metric, line=dict(color=C["blue"])))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 1], tickformat=".0%")))
    return _base(fig, title or f"{metric} by category")


def multi_radar(by_cat: dict[str, dict[str, Any]], metrics: list[str]) -> go.Figure:
    fig = go.Figure()
    for i, m in enumerate(metrics):
        cats = [c for c in by_cat if by_cat[c].get(m, {}).get("n")]
        if not cats:
            continue
        vals = [by_cat[c][m]["mean"] for c in cats]
        names = [c.replace("_", " ") for c in cats]
        fig.add_trace(go.Scatterpolar(r=[*vals, vals[0]], theta=[*names, names[0]], name=m, fill="toself", opacity=0.45,
                                      line=dict(color=CATS[i % len(CATS)])))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 1], tickformat=".0%")))
    return _base(fig, "Selected metrics across categories", 420)


def heatmap(rows: list[str], cols: list[str], z: list[list[float | None]], title: str, height: int | None = None) -> go.Figure:
    fig = go.Figure(go.Heatmap(z=z, x=cols, y=rows, zmin=0, zmax=1, colorscale=[[0, "#cf222e"], [0.5, "#f2cc60"], [1, "#2da44e"]],
                               hoverongaps=False, xgap=2, ygap=2, colorbar=dict(title="score")))
    fig.update_yaxes(autorange="reversed")
    return _base(fig, title, height or max(300, 22 * len(rows) + 120))


def timeline(events: list[dict[str, Any]]) -> go.Figure:
    colors = {"guard": C["purple"], "locate": C["blue"], "repro": C["amber"], "triage": C["grey"], "round": C["grey"],
              "node": C["green"], "critic": C["amber"], "done": C["blue"], "pr": C["green"], "error": C["red"]}
    fig = go.Figure()
    kinds = list(dict.fromkeys(e["type"] for e in events))
    for k in kinds:
        ev = [e for e in events if e["type"] == k]
        fig.add_trace(go.Scatter(x=[e["t_ms"] for e in ev], y=[k] * len(ev), mode="markers", name=k,
                                 marker=dict(size=13, color=colors.get(k, C["grey"]), symbol="diamond"),
                                 text=[_event_text(e) for e in ev], hoverinfo="text+x"))
    fig.update_xaxes(title="ms since run start")
    return _base(fig, "Event timeline", max(260, 40 * len(kinds) + 120))


def _event_text(e: dict[str, Any]) -> str:
    d = e.get("data", {})
    if e["type"] == "node":
        return f"node {d.get('id')}: {d.get('passed')}/{d.get('total')} tests, score {d.get('score')}, policy ok={d.get('policy', {}).get('ok')}"
    if e["type"] == "guard":
        return f"{d.get('stage')} guard: {d.get('verdict')} {d.get('reasons')}"
    return str({k: v for k, v in d.items() if k not in ("output_tail",)})[:140]


def delta_bars(rows: list[dict[str, Any]]) -> go.Figure:
    rows = [r for r in rows if r.get("delta") is not None]
    rows.sort(key=lambda r: r["delta"])
    fig = go.Figure(go.Bar(x=[r["delta"] for r in rows], y=[r["metric"] for r in rows], orientation="h",
                           marker_color=[C["green"] if r["good"] else (C["red"] if r["good"] is False else C["grey"]) for r in rows]))
    fig.update_xaxes(zeroline=True, zerolinewidth=2)
    return _base(fig, "Delta (B minus A)", max(260, 22 * len(rows) + 80))


def locator_bars(case_rows: list[dict[str, Any]]) -> go.Figure:
    fig = go.Figure()
    names = [r["case_id"] for r in case_rows]
    for key, label, color in (("id_based_context_precision", "precision", C["blue"]), ("id_based_context_recall", "recall", C["green"])):
        fig.add_trace(go.Bar(name=label, x=names, y=[r.get(key) for r in case_rows], marker_color=color))
    fig.update_layout(barmode="group")
    fig.update_yaxes(range=[0, 1.05])
    return _base(fig, "Locator precision / recall per case (ID based)")
