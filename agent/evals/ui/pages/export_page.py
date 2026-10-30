import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from evals.ui import common

st.title("Export")
run_id, data = common.pick_run("Run to export", key="ex_run")
if not data:
    st.stop()
s, rows, d = data["summary"], data["cases"], data["dir"]
common.fake_banner(s["mode"])


def csv_text() -> str:
    buf = io.StringIO()
    metrics = [n for n in s["metric_names"] if n not in ("latency_ms", "total_tokens", "ttfe_ms", "cost_usd")]
    w = csv.writer(buf)
    w.writerow(["case_id", "category", "difficulty", "final_stage", "solved", *metrics])
    for r in rows:
        w.writerow([r["case_id"], r["category"], r["difficulty"], r["final_stage"], r["solved"],
                    *[(r["metrics"].get(m, {}).get("score") if r["metrics"].get(m, {}).get("status") == "ok" else "") for m in metrics]])
    return buf.getvalue()


def text_of(name: str) -> str:
    try:
        return (d / name).read_text(encoding="utf-8")
    except OSError:
        return ""


c1, c2, c3 = st.columns(3)
c1.download_button("summary.json", json.dumps(s, indent=2, default=str), f"{run_id}-summary.json", "application/json", icon=":material/download:", width="stretch")
c2.download_button("cases.jsonl", text_of("cases.jsonl"), f"{run_id}-cases.jsonl", "application/jsonl", icon=":material/download:", width="stretch")
c3.download_button("per-case metrics CSV", csv_text(), f"{run_id}-metrics.csv", "text/csv", icon=":material/table:", width="stretch")
c4, c5, c6 = st.columns(3)
c4.download_button("report.md", text_of("report.md"), f"{run_id}-report.md", "text/markdown", icon=":material/description:", width="stretch")
c5.download_button("report.html", text_of("report.html"), f"{run_id}-report.html", "text/html", icon=":material/web:", width="stretch")
c6.download_button("run.json (config, versions)", text_of("run.json"), f"{run_id}-run.json", "application/json", icon=":material/info:", width="stretch")

tab_md, tab_html = st.tabs(["Markdown preview", "HTML preview"])
with tab_md:
    st.markdown(text_of("report.md") or "_report.md not found_")
with tab_html:
    html = text_of("report.html")
    if html:
        st.iframe(html, height=700)
    else:
        st.info("report.html not found.")
