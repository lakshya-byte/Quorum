import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import streamlit as st

from evals.ui import charts, common

st.title("Ragas analysis")
st.caption("PatchLoop mapped onto Ragas: the locator is retrieval, the PR body is generation, the agent team is an agent. "
           "Offline metrics always run; LLM metrics need the judge (and embeddings for two of them).")
run_id, data = common.pick_run("Run", key="rg_run")
if not data:
    st.stop()
s = data["summary"]
common.fake_banner(s["mode"])
rg = s["ragas"]
table = rg.get("table", [])
if not table:
    st.info("This run was made with --no-ragas, or ragas could not be imported.")
    st.stop()
meta = rg.get("meta", {})
st.caption(f"ragas {meta.get('version')}; compat shim stubbed: {', '.join(meta.get('compat_stubbed', [])) or 'nothing'}; "
           f"LLM metrics {'on' if meta.get('llm') else 'off'}, embeddings {'on' if meta.get('embeddings') else 'off'}")

ran = [r for r in table if r["status"] == "ran"]
skipped = [r for r in table if r["status"] in ("needs_judge", "needs_embeddings")]
k1, k2, k3 = st.columns(3)
k1.metric("Ragas metrics that ran", f"{len(ran)} / {len(table)}")
k2.metric("Skipped", len(skipped), help="needs_judge or needs_embeddings")
k3.metric("Cases scored", max((r["n"] for r in table), default=0))

tab_t, tab_c, tab_r, tab_l, tab_a, tab_m, tab_s = st.tabs(["Analysis table", "By category", "Radar", "Locator", "Agent metrics", "Coverage matrix", "Skipped"])
with tab_t:
    st.dataframe(pd.DataFrame([{"metric": r["metric"], "status": r["status"], "n": r["n"], "mean": r["mean"], "min": r["min"],
                                "family": r["family"], "measures for PatchLoop": r["what"], "interpretation": r["interpretation"]} for r in table]),
                 width="stretch", hide_index=True,
                 column_config={"mean": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                                "measures for PatchLoop": st.column_config.TextColumn(width="large"),
                                "interpretation": st.column_config.TextColumn(width="large")})
    st.plotly_chart(charts.metric_bars(ran, "Ragas mean score by metric (ran)"), width="stretch")
with tab_c:
    pick = st.multiselect("Metrics", [r["metric"] for r in ran], default=[r["metric"] for r in ran][:4], key="rg_cat_metrics")
    cats = sorted({c for r in ran for c in r["by_category"]})
    if pick and cats:
        z = [[next((r["by_category"].get(c) for r in ran if r["metric"] == m), None) for c in cats] for m in pick]
        st.plotly_chart(charts.heatmap(pick, [c.replace("_", " ") for c in cats], z, "Mean score by metric and category"), width="stretch")
    else:
        st.info("Pick at least one metric.")
with tab_r:
    options = [r["metric"] for r in ran if len(r["by_category"]) >= 3]
    if options:
        sel = st.multiselect("Metrics on the radar", options, default=options[:3], key="rg_radar")
        # per-category dict in the shape charts.multi_radar expects
        by_cat: dict[str, dict] = {}
        for r in ran:
            for c, v in r["by_category"].items():
                by_cat.setdefault(c, {})[r["metric"]] = {"mean": v, "n": 1}
        st.plotly_chart(charts.multi_radar(by_cat, sel), width="stretch")
    else:
        st.info("A radar needs a metric that ran in at least three categories. Run the whole suite to fill it.")
with tab_l:
    loc_rows = []
    for r in data["cases"]:
        scores = {e["metric"]: e["score"] for e in r["ragas"] if e["status"] == "ran"}
        if "id_based_context_precision" in scores:
            loc_rows.append({"case_id": r["case_id"], **scores})
    if loc_rows:
        st.plotly_chart(charts.locator_bars(loc_rows), width="stretch")
        st.dataframe(loc_rows, width="stretch", hide_index=True)
        st.caption("Locator cases run without the scripted file hint, so these numbers measure the real retrieval step "
                   "(the keyword locator in fake mode, the LLM locator in hybrid/live).")
    else:
        st.info("No retrieval metrics in this run (select the locator suite).")
with tab_a:
    ag = [r for r in ran if r["metric"] in ("tool_call_accuracy", "tool_call_f1")]
    if ag:
        by_cat = {}
        for r in ag:
            for c, v in r["by_category"].items():
                by_cat.setdefault(c, {})[r["metric"]] = {"mean": v, "n": 1}
        st.plotly_chart(charts.category_bars(by_cat, [r["metric"] for r in ag], "Tool-call accuracy and F1 by category"), width="stretch")
        st.caption("ToolCallAccuracy is strict: the called agent set must equal the expected set. ToolCallF1 gives partial credit.")
    else:
        st.info("No agent metrics ran.")
with tab_m:
    cov = pd.DataFrame(rg.get("coverage", []))
    if not cov.empty:
        st.dataframe(cov.rename(columns={"applies": "applies to PatchLoop", "status": "this run", "how": "how / why not"}),
                     width="stretch", hide_index=True,
                     column_config={"how / why not": st.column_config.TextColumn(width="large")})
        st.caption("Not applicable: ContextEntityRecall, NoiseSensitivity, SummarizationScore, SQL metrics and multimodal metrics have no honest "
                   "counterpart in a bug-fixing agent; the reason is in the last column.")
with tab_s:
    if skipped:
        for r in skipped:
            st.markdown(f"{common.chip(r['status'], 'warn')} **{r['metric']}**: {r['skip_reason'] or r['interpretation']}")
        st.info("Skipped means skipped: no score is estimated or substituted. Configure `EVAL_JUDGE_MODEL`, `NEBIUS_API_KEY` "
                "(and `EVAL_EMBED_MODEL` for AnswerCorrectness / AnswerRelevancy) and run with `--judge nebius`.")
    else:
        st.success("No Ragas metric was skipped.")
