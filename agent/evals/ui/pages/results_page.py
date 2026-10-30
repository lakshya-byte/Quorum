import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import streamlit as st

from evals.ui import charts, common

st.title("Results")
run_id, data = common.pick_run("Run", key="results_run")
if not data:
    st.stop()
s, rows = data["summary"], data["cases"]
common.fake_banner(s["mode"])

c1, c2, c3 = st.columns([2, 2, 1])
cats = c1.multiselect("Category", sorted({r["category"] for r in rows}), key="res_cat")
diffs = c2.multiselect("Difficulty", ["easy", "medium", "hard"], key="res_diff")
only_bad = c3.toggle("Failing only", value=False, key="res_bad")


def bad_metrics(r):
    return [n for n, m in r["metrics"].items() if m.get("passed") is False]


view = [r for r in rows if (not cats or r["category"] in cats) and (not diffs or r["difficulty"] in diffs)
        and (not only_bad or bad_metrics(r) or r["status"] != "ok")]
table = pd.DataFrame([{
    "result": "PASS" if not bad_metrics(r) and r["status"] == "ok" else "FAIL", "case": r["case_id"],
    "category": r["category"], "difficulty": r["difficulty"], "stage": r["final_stage"], "solved": r["solved"],
    "failed metrics": ", ".join(bad_metrics(r)) or "-"} for r in view])
st.caption(f"{len(view)} of {len(rows)} cases. Select a row to drill down.")
if table.empty:
    st.info("No cases match the filters.")
    st.stop()


def color(v):
    return "background-color: rgba(45,164,78,.25)" if v == "PASS" else ("background-color: rgba(207,34,46,.25)" if v == "FAIL" else "")


event = st.dataframe(table.style.map(color, subset=["result"]), width="stretch", hide_index=True,
                     on_select="rerun", selection_mode="single-row", key="res_table")
sel = event.selection.rows if event and event.selection else []
case_id = table.iloc[sel[0]]["case"] if sel else st.selectbox("Or pick a case", table["case"].tolist(), key="res_pick")
row = next(r for r in rows if r["case_id"] == case_id)
traces = common.load_traces_data(run_id).get(case_id, [])
st.subheader(case_id)
st.caption(row["title"])
if not traces:
    st.warning("No trace stored for this case (run was made with an older version or traces were deleted).")
    st.stop()
trial = st.radio("Trial", list(range(len(traces))), horizontal=True, key="res_trial") if len(traces) > 1 else 0
tr = traces[trial]
tabs = st.tabs(["Final answer", "Timeline", "Candidates", "Test output", "Metrics", "Agents called", "Raw trace"])
with tabs[0]:
    f = tr.get("final", {})
    st.markdown(f"{common.chip(tr['final_stage'], 'blue')} {common.chip('fix verified' if tr['solved'] else 'no verified fix', 'ok' if tr['solved'] else 'warn')}"
                f" {common.chip('status ' + tr['status'], 'ok' if tr['status'] == 'ok' else 'fail')}")
    if f.get("url"):
        st.markdown(f"PR: `{f['url']}` (branch `{f.get('branch')}`, #{f.get('number')}, {'updated' if f.get('updated') else 'new'}, "
                    f"{'simulated, demo repo' if f.get('fake') else 'real'})")
    if f.get("title"):
        st.markdown(f"**{f['title']}**")
    st.markdown((f.get("body") or "_no output_").replace("\n## ", "\n#### ").replace("## ", "#### ", 1) if (f.get("body") or "").startswith("## ") else (f.get("body") or "_no output_").replace("\n## ", "\n#### "))
    st.caption(f"Source of this text: {f.get('body_source', 'n/a')}")
with tabs[1]:
    st.plotly_chart(charts.timeline(tr["events"]), width="stretch")
    st.dataframe([{"t_ms": e["t_ms"], "event": e["type"], "data": str(e["data"])[:300]} for e in tr["events"]],
                 width="stretch", hide_index=True)
with tabs[2]:
    if not tr["candidates"]:
        st.info("No candidates were produced (the run stopped before the proposers).")
    for cand in tr["candidates"]:
        ok = cand["policy"]["ok"] and cand["security"].get("ok", True)
        head = (f"#{cand['id']} {'baseline (original code)' if cand['baseline'] else cand['idea']}: "
                f"{cand['passed']}/{cand['total']} tests, score {cand['score']}")
        with st.expander(head, expanded=cand["id"] == tr.get("best_id")):
            st.markdown(f"policy {common.chip('pass' if cand['policy']['ok'] else 'blocked', 'ok' if cand['policy']['ok'] else 'fail')} "
                        f"security {common.chip('pass' if cand['security'].get('ok', True) else 'blocked', 'ok' if cand['security'].get('ok', True) else 'fail')} "
                        f"files {', '.join(cand['changed_files']) or '-'}; {cand['lines_changed']} changed lines"
                        + (" (best)" if cand["id"] == tr.get("best_id") else ""))
            if cand["policy"]["reasons"]:
                st.error("; ".join(cand["policy"]["reasons"]))
            if cand["security"].get("new_findings"):
                st.error("; ".join(f"{f.get('test_id')} {f.get('severity')}: {f.get('text')}" for f in cand["security"]["new_findings"]))
            if cand["diff"]:
                st.code(cand["diff"], language="diff")
with tabs[3]:
    best = next((c for c in tr["candidates"] if c["id"] == tr.get("best_id")), None) or (tr["candidates"][-1] if tr["candidates"] else None)
    st.code((best or {}).get("output_tail") or tr.get("evidence") or "(no test output)", language="text")
with tabs[4]:
    st.dataframe([{"metric": n, "status": m["status"], "score": m["score"], "passed": m["passed"], "threshold": m["threshold"],
                   "reason": m["reason"]} for n, m in row["metrics"].items() if n not in ("latency_ms", "total_tokens", "ttfe_ms", "cost_usd")],
                 width="stretch", hide_index=True)
    ext = [{"framework": "DeepEval", **{k: r[k] for k in ("metric", "status", "score", "reason")}} for r in row["deepeval"]] + \
          [{"framework": "Ragas", **{k: r[k] for k in ("metric", "status", "score", "reason")}} for r in row["ragas"]]
    if ext:
        st.markdown("**DeepEval and Ragas results for this case**")
        st.dataframe(ext, width="stretch", hide_index=True)
with tabs[5]:
    st.dataframe([{"t_ms": t["t_ms"], "agent / tool": t["name"], "args": str(t["args"])} for t in tr["tool_calls"]],
                 width="stretch", hide_index=True)
    st.caption(f"Retrieved files: {', '.join(tr['retrieved_files']) or '-'}")
with tabs[6]:
    st.json({k: v for k, v in tr.items() if k != "events"}, expanded=False)
