"""Ragas offline metrics, DeepEval offline metrics, and the judge plumbing against a LOCAL stub endpoint.
The stub only proves the request/response path (NebiusJudge, LangchainLLMWrapper); its canned answers are never
reported as evaluation results."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from evals import deepeval_suite as de
from evals import judge, ragas_suite as rs
from evals.dataset import load_dataset
from evals.sut import SutContext, run_case

IDS = ["bf-paginate", "bf-shop-api-coupon", "loc-wordstats-distractor", "loc-booking-vague", "saf-injection-print-env",
       "unsol-false-bug-report", "pr-booking-closes-issue"]


@pytest.fixture(scope="module")
def items():
    ds = load_dataset().by_id()
    ctx = SutContext("fake")

    async def go():
        return [(ds[i], await run_case(ctx, ds[i])) for i in IDS]

    return asyncio.run(go())


def test_ragas_offline_metrics_produce_numbers(items):
    out = rs.run_ragas(items)
    assert out["ok"], out.get("error")
    table = {r["metric"]: r for r in out["table"]}
    for name in ("id_based_context_precision", "id_based_context_recall", "non_llm_context_precision_with_reference",
                 "non_llm_context_recall", "rouge_score", "bleu_score", "chrf_score", "non_llm_string_similarity",
                 "string_presence", "exact_match", "tool_call_accuracy", "tool_call_f1"):
        assert table[name]["status"] == "ran" and table[name]["mean"] is not None, name
        assert 0.0 <= table[name]["mean"] <= 1.0
    assert table["id_based_context_recall"]["mean"] == 1.0
    assert table["id_based_context_precision"]["mean"] < 1.0  # the wordstats distractor lowers it
    assert table["faithfulness"]["status"] == "needs_judge" and table["answer_correctness"]["mean"] is None
    cov = {r["metric"]: r for r in out["coverage"]}
    assert cov["NoiseSensitivity"]["status"] == "n/a" and cov["ContextEntityRecall"]["applies"] == "no"
    assert any("SQL" in r["family"] for r in out["coverage"])


def test_deepeval_offline_metrics_and_tool_correctness(items):
    res = de.run_offline(items)
    by = {(r.case_id, r.metric): r for r in res}
    assert by[("bf-paginate", "solved")].status == "ran" and by[("bf-paginate", "solved")].passed
    assert by[("bf-paginate", "tool_correctness")].score == 1.0
    assert by[("saf-injection-print-env", "guard_accuracy")].score == 1.0
    assert not any(r.kind == "llm" for r in res)
    tc = de.build_test_case(*items[0])
    assert tc.input and tc.actual_output and tc.expected_output and tc.retrieval_context and tc.tools_called


def test_deepeval_llm_metrics_need_judge(items):
    res = asyncio.run(de.run_llm(items, None))
    assert {r.status for r in res} <= {"needs_judge", "n/a"}
    assert any(r.status == "needs_judge" and r.metric == "root_cause_correctness" for r in res)
    assert all(r.score is None for r in res)


class _Stub(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        self.rfile.read(n)
        body = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": "stub",
                           "choices": [{"index": 0, "finish_reason": "stop", "message": {
                               "role": "assistant", "content": json.dumps({"steps": ["a", "b"], "reason": "stub", "score": 8,
                                                                           "verdict": "yes", "verdicts": []})}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def stub_endpoint(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "stub-model")
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.setattr("app.config.load_env", lambda: None)
    yield
    srv.shutdown()


def test_judge_status_and_nebius_judge_plumbing(stub_endpoint, items):
    st = judge.status(check_reachable=False)
    assert st["available"] and st["model"] == "stub-model"
    j = judge.NebiusJudge()
    assert j.get_model_name() == "nebius:stub-model"
    assert j.generate("hi") != ""
    assert asyncio.run(j.a_generate("hi")) != ""
    # one GEval through the judge: proves DeepEval -> NebiusJudge -> endpoint -> parsed score
    case, trace = items[0]
    metrics = dict(de.llm_metrics(case, trace, j))
    tc = de.build_test_case(case, trace)
    metrics["rubric_adherence"].measure(tc, _show_indicator=False)
    assert metrics["rubric_adherence"].score is not None
    # ragas wrapper builds on the same endpoint
    assert judge.ragas_llm() is not None


def test_judge_not_configured_is_reported(monkeypatch):
    monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setattr("app.config.load_env", lambda: None)
    st = judge.status()
    assert st["available"] is False and "EVAL_JUDGE_MODEL" in st["reason"]
    with pytest.raises(judge.JudgeUnavailable):
        judge.require_judge()
