import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import streamlit as st

from evals.deepeval_suite import LLM_METRIC_CATALOG, OFFLINE_NON_DET
from evals.ui import charts, common

st.title("DeepEval")
st.caption("LLMTestCases are built from each run's trace. Deterministic metrics (a custom `BaseMetric` subclass) and "
           "`ToolCorrectnessMetric` run offline. GEval, Faithfulness, AnswerRelevancy and TaskCompletion need the Nebius judge.")
run_id, data = common.pick_run("Run", key="de_run")
if not data:
    st.stop()
s = data["summary"]
common.fake_banner(s["mode"])
rows = s["deepeval"]
if not rows:
    st.info("This run was made with --no-deepeval.")
    st.stop()

ran = [r for r in rows if r["status"] == "ran"]
needs = [r for r in rows if r["status"] == "needs_judge"]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Metrics that ran", len(ran))
k2.metric("Skipped (needs_judge)", len(needs))
k3.metric("Mean pass rate (ran)", common.fmt(sum(r["pass_rate"] for r in ran if r["pass_rate"] is not None) / max(1, len([r for r in ran if r['pass_rate'] is not None])), pct=True))
k4.metric("Judge", s["judge"]["mode"], help=s["judge"].get("reason"))

st.subheader("Metric summary")
frame = pd.DataFrame([{"metric": r["metric"], "kind": r["kind"], "status": r["status"], "cases ran": r["ran"], "mean": r["mean"],
                       "min": r["min"], "pass rate": r["pass_rate"], "needs judge": r["needs_judge"]} for r in rows])
st.dataframe(frame, width="stretch", hide_index=True,
             column_config={"mean": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                            "pass rate": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})

if ran:
    st.plotly_chart(charts.metric_bars([r for r in rows if r["status"] == "ran"], "DeepEval mean score by metric"), width="stretch")

st.subheader("Case x metric")
cells: dict[tuple[str, str], float | None] = {}
for r in data["cases"]:
    for e in r["deepeval"]:
        if e["status"] == "ran":
            cells[(r["case_id"], e["metric"])] = e["score"]
metrics = sorted({m for _, m in cells})
case_ids = [r["case_id"] for r in data["cases"] if any((r["case_id"], m) in cells for m in metrics)]
if cells:
    st.plotly_chart(charts.heatmap(case_ids, metrics, [[cells.get((c, m)) for m in metrics] for c in case_ids], "Score per case and metric"),
                    width="stretch")

st.subheader("Judge-based metrics")
if needs:
    st.warning(f"{len(needs)} judge metric(s) were skipped with status **needs_judge** because {s['judge'].get('reason', 'no judge is configured')}. "
               "No score was invented. Set `NEBIUS_API_KEY` and `EVAL_JUDGE_MODEL` and run with `--judge nebius`.", icon=":material/gavel:")
st.dataframe([{"metric": k, "what it grades": v, "status": next((r["status"] for r in rows if r["metric"] == k), "n/a")}
              for k, v in {**LLM_METRIC_CATALOG, **OFFLINE_NON_DET}.items()], width="stretch", hide_index=True)
with st.expander("Run it from a terminal"):
    st.code("pytest evals/test_deepeval_golden.py            # offline metrics (judge metrics skip without a judge)\n"
            "deepeval test run evals/test_deepeval_golden.py # same, through the DeepEval runner (telemetry stays off)\n"
            "python -m evals.run --judge nebius              # judge metrics inside the pipeline", language="bash")
