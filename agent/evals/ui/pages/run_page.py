import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from evals.common import ENGINES, MODES
from evals.pipeline import SUITES, STAGES
from evals.ui import common

AGENT = Path(__file__).resolve().parents[3]
st.title("Run suite")
rd = common.results_dir()
active_file = rd / ".active_run.json"


def read_active() -> dict | None:
    try:
        return json.loads(active_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie child counts as finished
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return True


def tail(path: Path, n: int = 14) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def progress_of(run_dir: Path) -> tuple[float, str]:
    try:
        last = json.loads((run_dir / "progress.jsonl").read_text().splitlines()[-1])
    except (OSError, ValueError, IndexError):
        return 0.0, "starting"
    stage = last["stage"]
    i = STAGES.index(stage) if stage in STAGES else 0
    frac = (last["done"] / last["total"]) if last["total"] else 0
    return min(1.0, (i + frac) / len(STAGES)), f"{stage}: {last['done']}/{last['total']} {last['message']}"


@st.fragment(run_every=1)
def live_panel() -> None:
    act = read_active()
    if not act:
        st.caption("No run started from this app yet.")
        return
    run_dir = rd / act["run_id"]
    running = alive(act["pid"]) and not (run_dir / "summary.json").exists()
    frac, label = progress_of(run_dir)
    if running:
        st.progress(frac, text=f"{act['run_id']}  |  {label}")
        if st.button("Stop run", icon=":material/stop_circle:", key="stop_btn", type="secondary"):
            try:
                os.kill(act["pid"], signal.SIGTERM)
                st.warning("Stop signal sent. Partial traces are kept and can be resumed with --resume.")
            except OSError as exc:
                st.error(f"Could not stop the process: {exc}")
    else:
        done = (run_dir / "summary.json").exists()
        st.progress(1.0 if done else frac, text=f"{act['run_id']}  |  {'finished' if done else 'ended before finishing (stopped, refused or failed)'}")
        if done:
            from evals.pipeline import load_run

            data = load_run(act["run_id"], rd)
            if data:
                g = data["summary"]["gate"]
                st.markdown(common.gate_chip(g["passed"]) + f"  solve rate {common.fmt(data['summary']['headline'].get('solve_rate'), pct=True)}")
                st.cache_data.clear()
        else:
            st.error("The run ended without results. Log tail below.")
    with st.expander("Log", expanded=running):
        st.code(tail(run_dir / "ui.log", 25) or "(empty)", language="text")


idx = common.load_index()
act = read_active()
busy = bool(act and alive(act["pid"]) and not (rd / act["run_id"] / "summary.json").exists())

js = common.judge_status()
with st.form("run_form"):
    st.subheader("Configuration")
    a1, a2, a3 = st.columns(3)
    suite = a1.selectbox("Suite", list(SUITES), index=0, help="quick = 8 representative cases")
    mode = a2.radio("Mode", list(MODES), horizontal=True, help="fake: scripted agents; hybrid: real Nemotron + local sandbox; live: + Nebius Sandboxes")
    engine = a3.selectbox("Engine (bundled-bug cases)", list(ENGINES), index=2)
    try:
        all_ids = [c["id"] for c in common.load_dataset_dict()["cases"]]
    except Exception:
        all_ids = []
    ids = st.multiselect("Specific cases (overrides the suite)", all_ids)
    b1, b2, b3, b4 = st.columns(4)
    n = b1.slider("Repetitions per case (n)", 1, 10, 1)
    conc = b2.slider("Concurrency", 1, 8, 4)
    judge_on = b3.toggle("Use the Nebius judge", value=False, disabled=not js["available"],
                         help=js["reason"] if not js["available"] else "DeepEval GEval/Faithfulness and Ragas LLM metrics")
    update_base = b4.checkbox("Update baseline", value=False)
    submitted = st.form_submit_button("Start run", type="primary", icon=":material/play_arrow:", disabled=busy)

st.markdown("**Availability**  " + common.chip("fake ready", "ok"))
for m in ("hybrid", "live"):
    stt = common.mode_status(m)
    st.markdown(f"{m}: " + (common.chip("ready", "ok") if stt["ready"] else common.chip("unavailable", "warn") + f"  {stt['reason']}"))
st.markdown("**Judge**  " + (common.chip("configured", "ok") + f" `{js['model']}`" if js["available"] else
                              common.chip("not configured", "warn") + f" LLM metrics will be skipped as needs_judge. {js['reason']}"))
if mode == "fake":
    common.fake_banner("fake")

if submitted:
    refusal = None
    if mode != "fake" and not common.mode_status(mode)["ready"]:
        refusal = common.mode_status(mode)["reason"]
    if refusal:
        st.error(f"Refused: {refusal}. No fake numbers are substituted for a mode that cannot run here.", icon=":material/block:")
    else:
        from evals.common import new_run_id

        run_id = new_run_id(mode)
        (rd / run_id).mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "evals.run", "--mode", mode, "--engine", engine, "--suite", suite, "--n", str(n),
               "--concurrency", str(conc), "--run-id", run_id, "--results-dir", str(rd), "--judge", "nebius" if judge_on else "none", "-q"]
        if ids:
            cmd += ["--cases", ",".join(ids)]
        if update_base:
            cmd.append("--update-baseline")
        log = open(rd / run_id / "ui.log", "w")
        proc = subprocess.Popen(cmd, cwd=str(AGENT), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        active_file.write_text(json.dumps({"run_id": run_id, "pid": proc.pid, "started": time.time(), "cmd": cmd}))
        st.toast(f"Started {run_id}")
        st.rerun()

st.subheader("Progress")
live_panel()
