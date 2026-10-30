import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from evals.ui import charts, common

st.title("Overview")
idx = common.load_index()
if not idx:
    common.empty_state()
    st.stop()

latest = idx[0]
data = common.load_run_data(latest["run_id"])
if data is None:
    st.error(f"Latest run {latest['run_id']} is unreadable.")
    st.stop()
s = data["summary"]
common.fake_banner(s["mode"])
st.caption(f"Latest run `{s['run_id']}`: {s['cases']} cases, {s['trials']} trials, suite **{s['suite']}**, mode **{s['mode']}**, "
           f"engine {s['engine']}, dataset v{s['dataset_version']}")
st.markdown(common.gate_chip(s["gate"]["passed"]) + f"  baseline: {s['gate']['baseline']}")

h = s["headline"]
cols = st.columns(6)
cols[0].metric("Solve rate (pass@1)", common.fmt(h.get("solve_rate"), pct=True), f"{h.get('solves')}/{h.get('solve_trials')} trials", delta_color="off")
cols[1].metric("Guard TPR", common.fmt(h.get("guard_tpr"), pct=True), help="hostile inputs blocked")
cols[2].metric("Guard FPR", common.fmt(h.get("guard_fpr"), pct=True), help="benign inputs wrongly blocked")
cols[3].metric("Honest failure", common.fmt(h.get("honest_failure_rate"), pct=True))
cols[4].metric("Latency p95", f"{common.fmt(h.get('latency_p95_ms'))} ms")
cols[5].metric("Tokens / solve", common.fmt(h.get("tokens_per_solve")))

left, right = st.columns([3, 2])
with left:
    st.plotly_chart(charts.trend(idx), width="stretch")
with right:
    keys = ["solved", "outcome_match", "guard_accuracy", "policy_accuracy", "honest_failure", "tool_f1", "pr_body_completeness"]
    st.plotly_chart(charts.category_bars(s["by_category"], [k for k in keys[:3]], "Key metrics by category"), width="stretch")

with st.expander(f"Gate checks ({len(s['gate']['checks'])})", expanded=not s["gate"]["passed"]):
    for c in s["gate"]["checks"]:
        st.markdown(f"{common.chip('ok' if c['ok'] else 'FAIL', 'ok' if c['ok'] else 'fail')} **{c['kind']}** {c['message']}")

from evals.report import attention

att = attention(data["cases"])
st.subheader("Cases needing attention")
if att:
    st.dataframe([{"case": a["case_id"], "category": a["category"], "stage": a["stage"], "failed metrics": ", ".join(a["failed"]) or a["status"]}
                  for a in att], width="stretch", hide_index=True)
else:
    st.success("Every applicable metric passed its threshold.")

st.subheader("Recent runs")
st.dataframe([{"run": r["run_id"], "mode": r["mode"], "engine": r["engine"], "suite": r["suite"], "cases": r["cases"],
               "solve rate": r.get("solve_rate"), "guard TPR": r.get("guard_tpr"), "latency p95 ms": r.get("latency_p95_ms"),
               "judge": r.get("judge"), "gate": "pass" if r.get("gate_passed") else "FAIL"} for r in idx[:15]],
             width="stretch", hide_index=True,
             column_config={"solve rate": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                            "guard TPR": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
