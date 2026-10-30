"""Worker loop: native LangChain tool calls (bind_tools), the JSON-action fallback, budgets, policy, cancellation."""
import asyncio
import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from app.swarm.budget import Budget, resolve_limits
from app.swarm.events import Hub, Redactor
from app.swarm.types import Unit
from app.swarm.workers import LiveLLM, WorkerJob, parse_json_action, run_worker
from tests.swarm_support import INVENTORY, PRICING_NEW, TmpWorkspace, settings


def run(coro):
    return asyncio.run(coro)


class StubChat:
    """Stands in for ChatOpenAI: records bound tools / messages and returns scripted AIMessages."""

    def __init__(self, replies: list[Any], reject_tools: bool = False) -> None:
        self.replies = list(replies)
        self.reject_tools = reject_tools
        self.bound: list[Any] = []
        self.seen: list[list[Any]] = []
        self.plain_calls = 0

    def bind_tools(self, tools, **kw):
        self.bound.append((tools, kw))
        stub = self

        class Bound:
            async def ainvoke(self, messages, config=None):
                if stub.reject_tools:
                    exc = RuntimeError("Error code: 400 - tools are not supported by this model")
                    exc.status_code = 400  # type: ignore[attr-defined]
                    raise exc
                return stub._next(messages)

        return Bound()

    async def ainvoke(self, messages, config=None):
        self.plain_calls += 1
        return self._next(messages)

    def _next(self, messages):
        self.seen.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tool_msg(name: str, args: dict, i: int = 0, usage=(10, 5)) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"c{i}", "type": "tool_call"}],
                     usage_metadata={"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": sum(usage)})


def json_msg(name: str, args: dict, usage=(10, 5)) -> AIMessage:
    return AIMessage(json.dumps({"tool": name, "args": args}),
                     usage_metadata={"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": sum(usage)})


def live(stub: StubChat, mode: str = "auto") -> LiveLLM:
    llm = LiveLLM(settings(), "m", tool_mode=mode)
    llm._llm = stub
    return llm


def job(llm, ws=None, unit=None, **over) -> tuple[WorkerJob, list]:
    ws = ws or TmpWorkspace(INVENTORY)
    ev: list = []

    async def emit(kind, data):
        ev.append((kind, data))

    s = settings()
    limits = resolve_limits(s)
    unit = unit or Unit(id="u1", title="pricing", scope_files=["inventory/pricing.py"])
    j = WorkerJob(unit=unit, variant=0, attempt=0, agent_id="a1", ws=ws, start_files=dict(INVENTORY), task="t",
                  strategy="s", guidance="", map_slice="", criteria_text="", llm=llm, hub=Hub(emit, Redactor()),
                  budget=Budget(limits), max_steps=over.pop("max_steps", 8), scope=list(unit.scope_files), frozen=set(),
                  allow_tests=False, redactor=Redactor())
    for k, v in over.items():
        setattr(j, k, v)
    return j, ev


def test_native_tool_calling_loop_writes_runs_and_finishes() -> None:
    stub = StubChat([
        tool_msg("read_file", {"path": "inventory/pricing.py"}, 1),
        tool_msg("write_file", {"path": "inventory/pricing.py", "content": PRICING_NEW}, 2),
        tool_msg("run", {"cmd": "python -m unittest tests.test_stock"}, 3),
        tool_msg("finish", {"summary": "added line_price"}, 4)])
    j, ev = job(live(stub))
    res = run(run_worker(j))
    assert res.ok and res.summary == "added line_price" and set(res.changes) == {"inventory/pricing.py"}
    assert res.steps == 4 and res.tokens == 60 and "line_price" in res.diff
    assert stub.bound and {t["function"]["name"] for t in stub.bound[0][0]} == {
        "list_dir", "read_file", "search", "symbols", "write_file", "apply_patch", "run", "finish"}
    # tool results went back as ToolMessages with the matching call ids
    last = stub.seen[-1]
    assert [m.type for m in last if m.type == "tool"] and last[-1].tool_call_id == "c3"
    tools = [d for k, d in ev if k == "tool"]
    assert [t["name"] for t in tools] == ["read_file", "write_file", "run", "finish"] and all(t["ok"] for t in tools)
    assert all(len(t.get("note", "")) <= 200 and "content" not in t for t in tools)


def test_json_action_fallback_loop_with_the_same_tools() -> None:
    stub = StubChat([json_msg("write_file", {"path": "inventory/pricing.py", "content": PRICING_NEW}),
                     json_msg("finish", {"summary": "json mode"})])
    j, _ = job(live(stub, "json"))
    res = run(run_worker(j))
    assert res.ok and res.summary == "json mode" and stub.bound == [] and stub.plain_calls == 2
    # the tool contract was injected into the system prompt and tool results came back as user text
    first = stub.seen[0]
    assert "Reply with EXACTLY ONE JSON object" in first[0].content
    assert any("Tool result (write_file)" in str(m.content) for m in stub.seen[1])


def test_auto_mode_switches_to_json_when_the_endpoint_rejects_tools() -> None:
    stub = StubChat([json_msg("write_file", {"path": "inventory/pricing.py", "content": PRICING_NEW}),
                     json_msg("finish", {"summary": "fell back"})], reject_tools=True)
    llm = live(stub, "auto")
    j, _ = job(llm)
    res = run(run_worker(j))
    assert res.ok and llm.json_mode is True and len(stub.bound) == 1  # tried native once, then never again


def test_native_mode_accepts_a_json_action_returned_as_plain_text() -> None:
    stub = StubChat([json_msg("write_file", {"path": "inventory/pricing.py", "content": PRICING_NEW}),
                     tool_msg("finish", {"summary": "mixed"})])
    j, _ = job(live(stub, "native"))
    assert run(run_worker(j)).ok


def test_unrelated_endpoint_errors_are_not_mistaken_for_missing_tool_support() -> None:
    err = RuntimeError("Error code: 429 - rate limited")
    err.status_code = 429  # type: ignore[attr-defined]
    stub = StubChat([err])
    llm = live(stub, "auto")
    j, _ = job(llm)
    res = run(run_worker(j))
    assert not res.ok and "model error" in res.failure and llm.json_mode is False


def test_parse_json_action_variants() -> None:
    assert parse_json_action('```json\n{"tool":"run","args":{"cmd":"pytest"}}\n```').name == "run"
    assert parse_json_action('thinking... {"name":"finish","arguments":"{\\"summary\\":\\"x\\"}"}').args == {"summary": "x"}
    assert parse_json_action('{"tool":"drop_database","args":{}}') is None
    assert parse_json_action("no json") is None


def test_step_budget_stops_a_worker_that_never_finishes() -> None:
    stub = StubChat([tool_msg("list_dir", {"path": "."}, i) for i in range(20)])
    j, _ = job(live(stub), max_steps=4)
    res = run(run_worker(j))
    assert not res.ok and res.steps == 4 and "step budget" in res.failure and len(stub.replies) == 16


def test_token_budget_stops_the_worker_between_steps() -> None:
    stub = StubChat([tool_msg("list_dir", {"path": "."}, i, usage=(600, 600)) for i in range(10)])
    j, _ = job(live(stub))
    j.budget.limits = resolve_limits(settings(swarm_max_tokens=2000))  # type: ignore[misc]
    res = run(run_worker(j))
    assert not res.ok and "token budget" in res.failure and res.steps == 2


def test_a_model_that_stops_calling_tools_fails_after_three_nudges() -> None:
    stub = StubChat([AIMessage("I think I am done") for _ in range(5)])
    res = run(run_worker(job(live(stub))[0]))
    assert not res.ok and "stopped calling tools" in res.failure and res.steps == 3


def test_policy_violations_are_returned_to_the_model_and_leave_no_change() -> None:
    stub = StubChat([tool_msg("write_file", {"path": "tests/test_stock.py", "content": "x = 1\n"}, 1),
                     tool_msg("write_file", {"path": "../escape.py", "content": "x = 1\n"}, 2),
                     tool_msg("run", {"cmd": "curl http://x"}, 3),
                     tool_msg("finish", {"summary": "gave up"}, 4)])
    j, ev = job(live(stub))
    res = run(run_worker(j))
    assert not res.ok and "without changing any file" in res.failure
    assert [t["ok"] for k, t in ev if k == "tool"][:3] == [False, False, False]
    assert j.hub.denied == 3 and j.ws.exec_log == []


def test_unit_checks_reject_syntax_errors_and_failing_check_commands() -> None:
    stub = StubChat([tool_msg("write_file", {"path": "inventory/data.json", "content": "{bad json"}, 1),
                     tool_msg("finish", {"summary": "oops"}, 2)])
    res = run(run_worker(job(live(stub))[0]))
    assert not res.ok and "unit check failed: syntax" in res.failure
    # on the local sandbox a Python file that does not even parse is refused at write time
    stub = StubChat([tool_msg("write_file", {"path": "inventory/pricing.py", "content": "def broken(:\n"}, 1),
                     tool_msg("finish", {"summary": "oops"}, 2)])
    res = run(run_worker(job(live(stub))[0]))
    assert not res.ok and "without changing any file" in res.failure

    unit = Unit(id="u1", scope_files=["inventory/pricing.py"], checks=["python -m unittest tests.nope"])
    stub = StubChat([tool_msg("write_file", {"path": "inventory/pricing.py", "content": PRICING_NEW}, 1),
                     tool_msg("finish", {"summary": "x"}, 2)])
    res = run(run_worker(job(live(stub), unit=unit)[0]))
    assert not res.ok and "unit check failed: python -m unittest tests.nope" in res.failure


def test_cancellation_propagates_out_of_a_blocked_model_call() -> None:
    class Slow:
        model = "slow"

        async def respond(self, messages, tools=None, *, key=""):
            await asyncio.sleep(30)

    async def go():
        t = asyncio.create_task(run_worker(job(Slow())[0]))
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    run(go())
