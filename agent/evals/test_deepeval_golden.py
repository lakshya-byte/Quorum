"""DeepEval entry point:  pytest evals/test_deepeval_golden.py   |   deepeval test run evals/test_deepeval_golden.py

Traces come from a finished run (EVAL_RUN_ID=<run id>, default: the newest run in evals/results) or, when there is
none, from a fresh fake-mode execution of the golden dataset (scripted agents: validates the harness only).
Offline metrics always run through deepeval's assert_test. Judge metrics are skipped (not faked) without
EVAL_JUDGE_MODEL + NEBIUS_API_KEY. Telemetry is off (DEEPEVAL_TELEMETRY_OPT_OUT=YES).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import evals  # noqa: E402,F401
from evals import deepeval_suite as de  # noqa: E402
from evals import judge  # noqa: E402
from evals.common import RESULTS_DIR  # noqa: E402
from evals.dataset import load_dataset  # noqa: E402
from evals.pipeline import list_runs, load_traces  # noqa: E402
from evals.sut import SutContext, run_case  # noqa: E402

DS = load_dataset()
CASES = {c.id: c for c in DS.cases}


@pytest.fixture(scope="session")
def traces():
    run_id = os.environ.get("EVAL_RUN_ID") or next((r["run_id"] for r in list_runs(RESULTS_DIR)), "")
    loaded = load_traces(run_id, RESULTS_DIR) if run_id else {}
    if loaded:
        return {k: v[0] for k, v in loaded.items()}

    async def go():
        ctx = SutContext("fake")
        return {c.id: await run_case(ctx, c) for c in DS.cases}

    return asyncio.run(go())


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_golden_offline(case_id, traces):
    from deepeval import assert_test

    case, trace = CASES[case_id], traces.get(case_id)
    if trace is None:
        pytest.skip("case not in the loaded run")
    if "known-gap-heuristic" in case.tags and trace.mode == "fake":
        pytest.xfail("documented gap of the offline heuristic guard (see the case notes)")
    metrics = [m for _, _, m in de.offline_metrics(case, trace)]
    assert_test(de.build_test_case(case, trace), metrics)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_golden_judge(case_id, traces):
    if not judge.status()["available"]:
        pytest.skip("needs_judge: " + judge.status()["reason"])
    from deepeval import assert_test

    case, trace = CASES[case_id], traces.get(case_id)
    if trace is None:
        pytest.skip("case not in the loaded run")
    metrics = [m for _, m in de.llm_metrics(case, trace, judge.NebiusJudge())]
    if not metrics:
        pytest.skip("no judge metric applies to this case")
    assert_test(de.build_test_case(case, trace), metrics)
