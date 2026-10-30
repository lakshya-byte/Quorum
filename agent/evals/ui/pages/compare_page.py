import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import streamlit as st

from evals.ui import charts, common

st.title("Compare runs")
idx = common.load_index()
if len(idx) < 2:
    st.info("Comparing needs at least two runs. Start another one on the Run suite page.", icon=":material/compare_arrows:")
    if idx:
        common.empty_state() if not idx else None
    st.stop()

labels = {common.run_label(r): r["run_id"] for r in idx}
names = list(labels)
c1, c2 = st.columns(2)
a_label = c1.selectbox("Run A (baseline)", names, index=1, key="cmp_a")
b_label = c2.selectbox("Run B (candidate)", names, index=0, key="cmp_b")
A, B = common.load_run_data(labels[a_label]), common.load_run_data(labels[b_label])
if not A or not B:
    st.error("One of the runs could not be read.")
    st.stop()
sa, sb = A["summary"], B["summary"]
if sa["run_id"] == sb["run_id"]:
    st.warning("Pick two different runs.")
    st.stop()
if sa["mode"] != sb["mode"]:
    st.warning(f"Different modes ({sa['mode']} vs {sb['mode']}): deltas compare scripted agents with a model and are not a regression signal.")
elif sa["suite"] != sb["suite"] or sa["cases"] != sb["cases"]:
    st.info("The runs cover different case sets; only metrics present in both are compared.")
common.fake_banner("fake" if "fake" in (sa["mode"], sb["mode"]) else "")

g1, g2 = st.columns(2)
g1.markdown(f"**A** `{sa['run_id']}`  {common.gate_chip(sa['gate']['passed'])}")
g2.markdown(f"**B** `{sb['run_id']}`  {common.gate_chip(sb['gate']['passed'])}")

LOWER = {"regression_rate", "latency_ms", "total_tokens", "ttfe_ms", "cost_usd"}


def hint(name: str, a: dict, b: dict) -> str:
    """Two-proportion z hint for 0/1-like metrics; plain size hint otherwise. Informational, not a statistical test of the model."""
    na, nb = a.get("n", 0), b.get("n", 0)
    pa, pb = a.get("mean"), b.get("mean")
    if pa is None or pb is None or na < 2 or nb < 2:
        return "too few cases"
    se = math.sqrt(max(pa * (1 - pa), 0) / na + max(pb * (1 - pb), 0) / nb)
    if se == 0:
        return "identical" if pa == pb else "deterministic change"
    z = (pb - pa) / se
    return "significant (|z|>1.96)" if abs(z) > 1.96 else ("possible (|z|>1)" if abs(z) > 1 else "within noise")


rows = []
for name in sa["metric_names"]:
    if name not in sb["overall"] or name in ("latency_ms", "total_tokens", "ttfe_ms", "cost_usd"):
        continue
    a, b = sa["overall"].get(name, {}), sb["overall"].get(name, {})
    if a.get("mean") is None or b.get("mean") is None:
        continue
    d = b["mean"] - a["mean"]
    better = (d < 0) if name in LOWER else (d > 0)
    rows.append({"metric": name, "A": a["mean"], "B": b["mean"], "delta": d, "good": None if abs(d) < 1e-9 else better,
                 "n A/B": f"{a['n']}/{b['n']}", "hint": hint(name, a, b)})
head = []
for k in ("solve_rate", "guard_tpr", "guard_fpr", "honest_failure_rate", "latency_p50_ms", "latency_p95_ms", "tokens_per_solve"):
    va, vb = sa["headline"].get(k), sb["headline"].get(k)
    if va is not None and vb is not None:
        d = vb - va
        lower = k in ("guard_fpr", "latency_p50_ms", "latency_p95_ms", "tokens_per_solve")
        head.append({"metric": f"[headline] {k}", "A": va, "B": vb, "delta": d, "good": None if abs(d) < 1e-9 else ((d < 0) if lower else (d > 0)),
                     "n A/B": "-", "hint": ""})
allrows = head + rows
st.subheader("Deltas")
st.dataframe(pd.DataFrame(allrows).drop(columns=["good"]), width="stretch", hide_index=True,
             column_config={"delta": st.column_config.NumberColumn(format="%+.3f")})
changed = [r for r in rows if abs(r["delta"]) > 1e-9]
if changed:
    st.plotly_chart(charts.delta_bars(changed), width="stretch")
else:
    st.info("No metric changed between these runs (deterministic fake mode reproduces itself).")
st.caption("Hints are two-proportion z-scores treating each case as independent; with a few dozen deterministic cases treat them as a guide, "
           "not proof. Use --n > 1 and pass@k for model runs.")

st.subheader("Regressions and fixes (case level)")
oa, ob = sa.get("case_outcomes", {}), sb.get("case_outcomes", {})
common_ids = sorted(set(oa) & set(ob))
reg = [c for c in common_ids if oa[c] == 1 and ob[c] == 0]
fixed = [c for c in common_ids if oa[c] == 0 and ob[c] == 1]
r1, r2 = st.columns(2)
r1.metric("Regressed cases", len(reg), delta=f"-{len(reg)}" if reg else None, delta_color="inverse")
r2.metric("Fixed cases", len(fixed), delta=f"+{len(fixed)}" if fixed else None)
if reg:
    st.error("Regressed: " + ", ".join(reg))
if fixed:
    st.success("Fixed: " + ", ".join(fixed))
if not reg and not fixed:
    st.info("No case changed outcome between the two runs.")

st.subheader("Gate verdicts")
t1, t2 = st.columns(2)
for col, s in ((t1, sa), (t2, sb)):
    with col:
        for c in s["gate"]["checks"]:
            if not c["ok"]:
                st.markdown(f"{common.chip('FAIL', 'fail')} {c['message']}")
        if s["gate"]["passed"]:
            st.markdown(common.chip("all checks ok", "ok"))
