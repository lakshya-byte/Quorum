"""LiveTeam logic offline: real parsing/retry code, with langchain's fake chat model instead of Nebius."""
import asyncio

from langchain_core.language_models.fake_chat_models import FakeListChatModel

import app.agents as agents
from app.agents import LiveTeam, chat_model, parse_proposal
from app.bugs import BUGS
from app.config import Settings

S = Settings(nebius_api_key="dummy", model_nano="nano-x", model_super="super-x", mode="hybrid")
BUG = BUGS["average"]


def use_replies(monkeypatch, replies: list[str]) -> None:
    fake = FakeListChatModel(responses=replies)
    monkeypatch.setattr(agents, "chat_model", lambda settings, model, temperature=0.7: fake)


def test_chat_model_builds_offline_and_is_cached() -> None:
    m = chat_model(S, "nano-x")
    assert m.model_name == "nano-x" and m.max_tokens == 900
    assert str(m.openai_api_base).startswith("https://api.tokenfactory.nebius.com")
    assert chat_model(S, "nano-x") is m  # one client per model per process


def test_triage_retries_once_on_invalid_json(monkeypatch) -> None:
    use_replies(monkeypatch, [
        "sure! here are ideas",  # invalid -> corrective retry
        '```json\n{"cause": "integer division", "strategies": ["a", "b", "c"]}\n```',
    ])
    out, _ = asyncio.run(LiveTeam(S).triage(BUG, None))
    assert out.cause == "integer division" and out.strategies == ["a", "b", "c"]


def test_triage_falls_back_after_two_bad_replies(monkeypatch) -> None:
    use_replies(monkeypatch, ["nope", '{"cause": "x", "strategies": ["same", "same", "same"]}'])
    out, _ = asyncio.run(LiveTeam(S).triage(BUG, None))
    assert len(out.strategies) == 3 and out.cause == "(triage unavailable)"


def test_propose_parses_idea_and_code_and_strips_think(monkeypatch) -> None:
    reply = "<think>long reasoning ```python\nx=1\n```</think>\nIdea: guard empty input\n```python\n" + BUG["correct"] + "```"
    use_replies(monkeypatch, [reply])
    root = {"id": 0, "depth": 0, "code": BUG["buggy"], "output": "FAILED"}
    p = asyncio.run(LiveTeam(S).propose(BUG, "edge cases", root, "", "", 1, 0, None))
    assert p.idea == "guard empty input" and p.code == BUG["correct"] and p.model == "nano-x"
    assert p.extra_files == {}


def test_model_routing_nano_then_super() -> None:
    team = LiveTeam(S)
    assert team.model("triage") == "nano-x" and team.model("proposer", 1) == "nano-x"
    assert team.model("proposer", 2) == "super-x" and team.model("critic") == "super-x"
    assert LiveTeam(S, "ultra").model("proposer", 1) == "ultra"


def test_test_file_in_reply_is_reported_for_the_policy_gate() -> None:
    reply = ("Idea: x\n```python\n" + BUG["correct"] + "```\n```python\nimport unittest\n\n"
             "class T(unittest.TestCase):\n    def test_a(self):\n        pass\n```")
    _, code, extra = parse_proposal(reply, BUG)
    assert code == BUG["correct"] and "test_stats.py" in extra


def test_critic_lesson_and_reviewer(monkeypatch) -> None:
    use_replies(monkeypatch, [
        '{"lesson": "Return 0.0 for an empty list."}',
        '```json\n{"title": "fix: average", "body": "Fixes it.", "risk": "low"}\n```',
    ])
    team = LiveTeam(S)
    lesson, _, model = asyncio.run(team.critic(BUG, {"id": 3, "code": BUG["partial"], "output": "FAIL: test_x"}, None))
    assert lesson == "Return 0.0 for an empty list." and model == "super-x"
    review, _, _ = asyncio.run(team.review(BUG, {"idea": "i", "passed": 6, "total": 6, "code": "c"}, "sandbox", None))
    assert review.title == "fix: average"
