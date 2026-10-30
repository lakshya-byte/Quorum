"""Shared Streamlit helpers: paths, cached loaders, sidebar, chips, small formatters."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_AGENT = Path(__file__).resolve().parents[2]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from evals.common import FAKE_BANNER, GOLDEN_PATH, RESULTS_DIR, read_json  # noqa: E402

PALETTE = {"blue": "#2f81f7", "green": "#2da44e", "red": "#cf222e", "amber": "#bf8700", "grey": "#8c959f",
           "purple": "#8250df", "teal": "#1b7c83"}
CAT_COLORS = ["#2f81f7", "#2da44e", "#8250df", "#bf8700", "#cf222e", "#1b7c83", "#d1672b", "#6e7781"]


def results_dir() -> Path:
    return Path(os.environ.get("EVALS_RESULTS_DIR") or RESULTS_DIR)


def golden_path() -> Path:
    return Path(os.environ.get("EVALS_GOLDEN_PATH") or GOLDEN_PATH)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def _index(path: str, mtime: float) -> list[dict[str, Any]]:
    return read_json(Path(path), []) or []


def load_index() -> list[dict[str, Any]]:
    p = results_dir() / "index.json"
    return _index(str(p), _mtime(p))


@st.cache_data(show_spinner=False)
def _run(path: str, mtime: float) -> dict[str, Any] | None:
    from evals.pipeline import load_run

    d = Path(path)
    return load_run(d.name, d.parent)


def load_run_data(run_id: str) -> dict[str, Any] | None:
    d = results_dir() / run_id
    return _run(str(d), _mtime(d / "summary.json"))


@st.cache_data(show_spinner=False)
def _traces(path: str, mtime: float) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for p in sorted(Path(path).glob("*.json")):
        data = read_json(p)
        if data:
            out.setdefault(data["case_id"], []).append(data)
    return out


def load_traces_data(run_id: str) -> dict[str, list[dict[str, Any]]]:
    d = results_dir() / run_id / "traces"
    return _traces(str(d), _mtime(d))


@st.cache_data(show_spinner=False)
def _dataset(path: str, mtime: float) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_dataset_dict() -> dict[str, Any]:
    p = golden_path()
    return _dataset(str(p), _mtime(p))


@st.cache_data(ttl=30, show_spinner=False)
def judge_status() -> dict[str, Any]:
    from evals import judge

    return judge.status(check_reachable=False)


@st.cache_data(ttl=60, show_spinner=False)
def mode_status(mode: str) -> dict[str, Any]:
    """{ready, reason}: whether hybrid/live can honestly run here (fake always can)."""
    import asyncio

    from evals.sut import LiveUnavailable, preflight

    try:
        asyncio.run(preflight(mode))
        return {"ready": True, "reason": ""}
    except LiveUnavailable as exc:
        return {"ready": False, "reason": str(exc)}
    except Exception as exc:
        return {"ready": False, "reason": f"{type(exc).__name__}: {exc}"}


def fake_banner(mode: str) -> None:
    if mode == "fake":
        st.warning("**FAKE MODE**: scripted agents: validates the harness, not model quality. These numbers check the dataset, "
                   "sandbox, policy gate, metrics and reports. Use hybrid/live with a judge for model results.",
                   icon=":material/science:")


def chip(label: str, kind: str = "grey") -> str:
    """Markdown badge, e.g. :green-badge[PASS]."""
    color = {"ok": "green", "pass": "green", "ran": "green", "fail": "red", "error": "red", "warn": "orange",
             "skip": "gray", "grey": "gray", "blue": "blue"}.get(kind, kind)
    return f":{color}-badge[{label}]"


def gate_chip(passed: bool | None) -> str:
    return chip("GATE PASSED", "green") if passed else (chip("GATE FAILED", "red") if passed is False else chip("NO GATE", "grey"))


def fmt(v: Any, nd: int = 2, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float) and v != v:
        return "n/a"
    if pct:
        return f"{v:.0%}"
    if isinstance(v, float):
        return f"{v:,.{nd}f}" if abs(v) < 1000 else f"{v:,.0f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def run_label(row: dict[str, Any]) -> str:
    sr = row.get("solve_rate")
    return (f"{row['run_id']}  |  {row['mode']}/{row['engine']}  |  {row['suite']}  |  solve "
            f"{'n/a' if sr is None else f'{sr:.0%}'}  |  {'gate ok' if row.get('gate_passed') else 'gate FAIL'}")


def pick_run(label: str = "Run", key: str = "run", default_index: int = 0) -> tuple[str | None, dict[str, Any] | None]:
    idx = load_index()
    if not idx:
        empty_state()
        return None, None
    labels = {run_label(r): r["run_id"] for r in idx}
    choice = st.selectbox(label, list(labels), index=min(default_index, len(labels) - 1), key=key)
    run_id = labels[choice]
    data = load_run_data(run_id)
    if data is None:
        st.error(f"Run {run_id} could not be read (summary.json missing or corrupt).")
        return run_id, None
    return run_id, data


def empty_state() -> None:
    st.info("No eval runs yet. Start one on the **Run suite** page, or from a terminal: "
            "`python -m evals.run --suite quick`.", icon=":material/inbox:")
    try:
        st.page_link("ui/pages/run_page.py", label="Go to Run suite", icon=":material/play_arrow:")
    except Exception:  # page not registered (page rendered standalone)
        pass


def metric_frame(summary: dict[str, Any], names: list[str] | None = None) -> pd.DataFrame:
    rows = []
    for name in names or summary["metric_names"]:
        o = summary["overall"].get(name, {})
        if o.get("n"):
            rows.append({"metric": name, "n": o["n"], "mean": o["mean"], "pass_rate": o.get("pass_rate"),
                         **{c: g.get(name, {}).get("mean") for c, g in summary["by_category"].items()}})
    return pd.DataFrame(rows)


def sidebar() -> None:
    idx = load_index()
    js = judge_status()
    with st.sidebar:
        st.markdown("### PatchLoop evals")
        st.caption("Tests are the judge. Golden dataset, DeepEval, Ragas, regression gate.")
        latest = idx[0] if idx else None
        try:
            ds = load_dataset_dict()
            st.markdown(f"**Dataset** v{ds['dataset_version']}  \n{len(ds['cases'])} cases, schema {ds['schema_version']}")
        except Exception as exc:
            st.error(f"dataset unreadable: {exc}")
        if latest:
            st.markdown(f"**Latest run** `{latest['run_id'][-18:]}`  \nmode **{latest['mode']}**, engine {latest['engine']}  \n"
                        f"{gate_chip(latest.get('gate_passed'))}")
            if latest["mode"] == "fake":
                st.markdown(chip("FAKE MODE", "orange") + " harness validation only")
        else:
            st.caption("No runs yet.")
        st.markdown("**Judge** " + (chip("configured", "green") + f"  \n`{js['model']}`" if js["available"]
                                    else chip("not configured", "grey") + "  \nLLM metrics are skipped (needs_judge)."))
        if not js["available"]:
            st.caption(js["reason"])
        if st.button("Refresh data", icon=":material/refresh:", width="stretch"):
            st.cache_data.clear()
            st.rerun()
