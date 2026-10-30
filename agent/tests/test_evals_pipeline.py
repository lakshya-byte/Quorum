"""Pipeline smoke in fake mode (real graph engine, real sandbox), gate, baseline, refusal, resume."""
import copy
import json
from pathlib import Path

import pytest

from evals.judge import JudgeUnavailable
from evals.pipeline import (RunConfig, baseline_from_summary, evaluate_gate, load_thresholds, run_pipeline, select_cases)
from evals.dataset import load_dataset
from evals.sut import LiveUnavailable

SMOKE = ["bf-paginate", "bf-booking-backtoback", "loc-booking-vague", "saf-injection-print-env", "unsol-infra-feature-request",
         "fu-wordstats-docstring"]


@pytest.fixture(scope="session")
def smoke_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("evals-results")
    summary = run_pipeline(RunConfig(case_ids=SMOKE, results_dir=d, baseline="none"))
    return d, summary


def test_smoke_writes_all_result_files(smoke_run):
    d, s = smoke_run
    run_dir = Path(s["_run_dir"])
    for name in ("run.json", "cases.jsonl", "summary.json", "report.md", "report.html"):
        assert (run_dir / name).is_file(), name
    assert len(list((run_dir / "traces").glob("*.json"))) == len(SMOKE)
    idx = json.loads((d / "index.json").read_text())
    assert idx[0]["run_id"] == s["run_id"]
    assert s["cases"] == 6 and s["mode"] == "fake" and s["fake_banner"]
    assert "FAKE MODE" in (run_dir / "report.md").read_text() and "FAKE MODE" in (run_dir / "report.html").read_text()
    assert s["integrity"]["ok"] is True
    assert s["overall"]["solved"]["mean"] == 1.0
    assert s["by_category"]["safety_guardrails"]["guard_accuracy"]["mean"] == 1.0
    assert "bug_fix_single_file" in s["by_category"] and "easy" in s["by_difficulty"]
    rows = [json.loads(line) for line in (run_dir / "cases.jsonl").read_text().splitlines()]
    assert {r["case_id"] for r in rows} == set(SMOKE)


def test_llm_metrics_are_skipped_not_faked(smoke_run):
    _, s = smoke_run
    assert s["judge"]["mode"] == "none"
    skipped = [r for r in s["deepeval"] if r["kind"] == "llm" and r["status"] == "needs_judge"]
    assert skipped and all(r["mean"] is None for r in skipped)
    rg = {r["metric"]: r for r in s["ragas"]["table"]}
    assert rg["faithfulness"]["status"] == "needs_judge" and rg["faithfulness"]["mean"] is None
    assert rg["id_based_context_recall"]["status"] == "ran" and rg["tool_call_f1"]["mean"] is not None


def test_regression_gate_fails_on_degraded_run(smoke_run):
    _, s = smoke_run
    th = load_thresholds()
    base = baseline_from_summary(s)
    assert evaluate_gate(s, base, "self", th)["passed"] is True
    degraded = copy.deepcopy(s)
    degraded["overall"]["solved"]["mean"] = 0.5
    degraded["case_outcomes"]["bf-paginate"] = 0
    gate = evaluate_gate(degraded, base, "self", th)
    assert gate["passed"] is False
    kinds = {(c["kind"], c["metric"]) for c in gate["checks"] if not c["ok"]}
    assert ("regression", "solved") in kinds and ("case_flips", "case_outcomes") in kinds
    assert ("absolute", "solved") in kinds


def test_gate_baseline_mode_mismatch_skips_regression(smoke_run):
    _, s = smoke_run
    base = baseline_from_summary(s)
    base["mode"] = "live"
    gate = evaluate_gate(s, base, "x", load_thresholds())
    assert any(c.get("skipped") and "live" in c["message"] for c in gate["checks"])


def test_update_baseline_and_gate_through_pipeline(tmp_path, monkeypatch):
    import evals.pipeline as p

    monkeypatch.setattr(p, "BASELINES_DIR", tmp_path / "baselines")
    ids = ["bf-paginate", "bf-slugify"]
    first = run_pipeline(RunConfig(case_ids=ids, results_dir=tmp_path, update_baseline=True, deepeval=False, ragas=False, integrity=False))
    assert (tmp_path / "baselines" / "fake-baseline.json").is_file()
    second = run_pipeline(RunConfig(case_ids=ids, results_dir=tmp_path, deepeval=False, ragas=False, integrity=False))
    assert second["gate"]["baseline"].endswith("fake-baseline.json") and second["gate"]["passed"]


def test_resume_reuses_traces(tmp_path):
    ids = ["bf-average"]
    a = run_pipeline(RunConfig(case_ids=ids, results_dir=tmp_path, deepeval=False, ragas=False, integrity=False, baseline="none"))
    b = run_pipeline(RunConfig(case_ids=ids, results_dir=tmp_path, resume=a["run_id"], deepeval=False, ragas=False,
                               integrity=False, baseline="none"))
    ta = json.loads(next((Path(a["_run_dir"]) / "traces").glob("*.json")).read_text())
    tb = json.loads(next((Path(b["_run_dir"]) / "traces").glob("*.json")).read_text()) if (Path(b["_run_dir"]) / "traces").exists() else ta
    assert ta["case_id"] == tb["case_id"] and b["overall"]["solved"]["mean"] == 1.0


def test_n_repetitions_give_pass_at_k(tmp_path):
    s = run_pipeline(RunConfig(case_ids=["bf-cart"], n=2, results_dir=tmp_path, deepeval=False, ragas=False, integrity=False, baseline="none"))
    assert s["trials"] == 2 and s["overall"]["pass_at_k"]["mean"] == 1.0


def test_live_and_judge_refuse_honestly(tmp_path, monkeypatch):
    for k in ("NEBIUS_API_KEY", "MODEL_NANO", "EVAL_JUDGE_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("app.config.load_env", lambda: None)
    with pytest.raises(LiveUnavailable):
        run_pipeline(RunConfig(mode="hybrid", case_ids=["bf-paginate"], results_dir=tmp_path))
    with pytest.raises(JudgeUnavailable):
        run_pipeline(RunConfig(judge="nebius", case_ids=["bf-paginate"], results_dir=tmp_path))
    assert not list(tmp_path.glob("*/summary.json"))


def test_select_cases_suites():
    ds = load_dataset()
    assert {c.category for c in select_cases(ds, "safety")} == {"safety_guardrails"}
    assert len(select_cases(ds, "quick")) == 8 and len(select_cases(ds, "all")) == len(ds.cases)
    assert {c.category for c in select_cases(ds, "bugs,locator")} == {"bug_fix_single_file", "locator_retrieval"}
    with pytest.raises(ValueError):
        select_cases(ds, "nope")


def test_cli_exit_codes(tmp_path, monkeypatch, capsys):
    from evals.run import main

    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setattr("app.config.load_env", lambda: None)
    assert main(["--mode", "live", "--results-dir", str(tmp_path), "-q"]) == 3
    assert "REFUSED" in capsys.readouterr().err
    assert main(["--cases", "bf-paginate", "--results-dir", str(tmp_path), "--no-integrity", "--no-ragas", "--no-deepeval",
                 "--baseline", "none", "-q"]) == 0
    assert main(["--suite", "zzz", "--results-dir", str(tmp_path)]) == 2
