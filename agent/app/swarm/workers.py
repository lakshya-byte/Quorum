"""LLM adapters (native tool calling via LangChain `bind_tools`, JSON-action fallback) and the worker agent loop.

Native tool calling on the Nebius endpoint is UNVERIFIED from this build environment (api.tokenfactory.nebius.com is
unreachable here), hence the fallback: when the endpoint rejects `tools`, or the model answers with a JSON action in
plain text, the same tool set is driven through `{"tool": ..., "args": {...}}` replies. `SWARM_TOOL_MODE=json` forces it.
"""
from __future__ import annotations

import ast
import asyncio
import difflib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.swarm.budget import Budget
from app.swarm.events import DIFF_MAX, Hub, Redactor
from app.swarm.prompts import JSON_TOOL_SYSTEM, WORKER_SYSTEM, worker_user
from app.swarm.tools import TOOL_NAMES, TOOL_SPECS, ToolBox, check_command
from app.swarm.types import Unit, WorkerResult

log = logging.getLogger(__name__)

WORKER_MAX_OUTPUT = 4096
PLANNER_MAX_OUTPUT = 3500
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```[ \t]*[\w+-]*[ \t]*\n(.*?)```", re.DOTALL)


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})


class ChatLLM(Protocol):
    model: str

    async def respond(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
                      key: str = "") -> LLMReply: ...


# ---- JSON action parsing --------------------------------------------------------------------

def _balanced_objects(text: str) -> list[str]:
    out, depth, start, in_str, esc = [], 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                out.append(text[start:i + 1])
    return out


def parse_json_any(reply: str) -> Any | None:
    """First JSON value in a model reply (fenced block or bare object); None when there is none."""
    body = _THINK.sub("", reply or "")
    candidates = [m.group(1) for m in _FENCE.finditer(body)] + _balanced_objects(body)
    for c in candidates:
        try:
            return json.loads(c)
        except ValueError:
            continue
    return None


def parse_json_action(reply: str) -> ToolCall | None:
    data = parse_json_any(reply)
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return None
    name = data.get("tool") or data.get("name") or data.get("action")
    args = data.get("args", data.get("arguments", data.get("input", data.get("parameters", {}))))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if isinstance(name, str) and name in TOOL_NAMES and isinstance(args, dict):
        return ToolCall(id=f"json-{abs(hash(reply)) % 10**8}", name=name, args=args)
    return None


# ---- live adapter ---------------------------------------------------------------------------

def _tools_unsupported(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    return (status in (400, 404, 405, 422, 501) and ("tool" in text or "function" in text)) or \
        "does not support tool" in text or "tools is not supported" in text or "tool_choice" in text


class LiveLLM:
    """ChatOpenAI against the Nebius endpoint. `tool_mode`: auto | native | json."""

    def __init__(self, settings: Any, model: str, *, temperature: float = 0.2, max_tokens: int = WORKER_MAX_OUTPUT,
                 tool_mode: str = "auto", config_factory: Any = None) -> None:
        self.settings = settings
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = tool_mode == "json"
        self.forced_native = tool_mode == "native"
        self.config_factory = config_factory
        self._llm: Any = None

    def _chat(self) -> Any:
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            from app.agents import _shared_http
            from app.config import NEBIUS_BASE_URL

            s = self.settings
            self._llm = ChatOpenAI(model=self.model, base_url=NEBIUS_BASE_URL, api_key=s.nebius_api_key,
                                   temperature=self.temperature, max_tokens=self.max_tokens, timeout=s.llm_timeout * 2,
                                   max_retries=1, http_async_client=_shared_http(), stream_usage=True)
        return self._llm

    def _config(self, key: str) -> Any:
        cfg = dict(self.config_factory(key)) if self.config_factory else {}
        cfg.setdefault("run_name", f"swarm-{key.split(':')[0] or 'llm'}")
        return cfg

    @staticmethod
    def _to_lc(messages: list[dict[str, Any]], native: bool) -> list[Any]:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        out: list[Any] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                out.append(SystemMessage(m["content"]))
            elif role == "user":
                out.append(HumanMessage(m["content"]))
            elif role == "assistant":
                calls = m.get("tool_calls") or []
                if native and calls:
                    out.append(AIMessage(m.get("content") or "", tool_calls=[
                        {"name": c["name"], "args": c["args"], "id": c["id"], "type": "tool_call"} for c in calls]))
                elif calls:
                    out.append(AIMessage(json.dumps({"tool": calls[0]["name"], "args": calls[0]["args"]})))
                else:
                    out.append(AIMessage(m.get("content") or ""))
            elif role == "tool":
                if native:
                    out.append(ToolMessage(m["content"], tool_call_id=m["tool_call_id"]))
                else:
                    out.append(HumanMessage(f"Tool result ({m.get('name', 'tool')}):\n{m['content']}"))
        return out

    async def respond(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
                      key: str = "") -> LLMReply:
        from app.agents import _usage

        use_native = bool(tools) and not self.json_mode
        if use_native:
            try:
                bound = self._chat().bind_tools(tools, tool_choice="auto")
                msg = await bound.ainvoke(self._to_lc(messages, True), config=self._config(key))
                calls = [ToolCall(str(c.get("id") or f"call-{i}"), str(c["name"]), c.get("args") or {})
                         for i, c in enumerate(getattr(msg, "tool_calls", None) or [])]
                content = _flat(msg.content)
                if not calls:
                    action = parse_json_action(content)  # a model that answers with the JSON action as text
                    if action:
                        calls = [action]
                return LLMReply(content, calls, _usage(msg))
            except Exception as exc:
                if self.forced_native or not _tools_unsupported(exc):
                    raise
                log.warning("endpoint rejected native tool calling (%s); switching to the JSON action loop",
                            type(exc).__name__)
                self.json_mode = True
        msgs = messages
        if tools:
            msgs = [{"role": "system", "content": messages[0]["content"] + "\n\n" + JSON_TOOL_SYSTEM}, *messages[1:]]
        reply = await self._chat().ainvoke(self._to_lc(msgs, False), config=self._config(key))
        content = _flat(reply.content)
        calls = []
        if tools:
            action = parse_json_action(content)
            calls = [action] if action else []
        return LLMReply(content, calls, _usage(reply))


def _flat(content: Any) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


# ---- worker ---------------------------------------------------------------------------------

@dataclass
class WorkerJob:
    unit: Unit
    variant: int
    attempt: int
    agent_id: str
    ws: Any
    start_files: dict[str, str]  # the unit's starting state (path -> text)
    task: str
    strategy: str
    guidance: str
    map_slice: str
    criteria_text: str
    llm: ChatLLM
    hub: Hub
    budget: Budget
    max_steps: int
    scope: list[str]
    frozen: set[str]
    allow_tests: bool
    redactor: Redactor
    isolation: str = "local"
    note: str = ""


def make_diff(before: dict[str, str | None], after: dict[str, str | None], limit: int = DIFF_MAX) -> str:
    chunks = []
    for path in sorted(after):
        old = (before.get(path) or "").splitlines(keepends=True)
        new = (after[path] or "").splitlines(keepends=True)
        chunks.append("".join(difflib.unified_diff(old, new, f"a/{path}", f"b/{path}")))
    return "".join(chunks)[:limit]


def syntax_problem(path: str, text: str) -> str:
    try:
        if path.endswith(".py"):
            ast.parse(text)
        elif path.endswith(".json"):
            json.loads(text)
    except (SyntaxError, ValueError) as exc:
        return f"{path}: {type(exc).__name__}: {str(exc)[:120]}"
    return ""


async def unit_checks(ws: Any, unit: Unit, changes: dict[str, str | None]) -> tuple[bool, list[dict[str, Any]]]:
    """Cheap unit-level gate: syntax of changed files, then the unit's own allow-listed check commands."""
    results: list[dict[str, Any]] = []
    for path, text in changes.items():
        if text is not None:
            prob = syntax_problem(path, text)
            if prob:
                results.append({"check": "syntax", "ok": False, "detail": prob})
    if results:
        return False, results
    for cmd in unit.checks[:4]:
        bad = check_command(cmd)
        if bad:
            results.append({"check": cmd, "ok": True, "detail": f"skipped (not allow-listed: {bad})"})
            continue
        try:
            res = await ws.exec(cmd, 120)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            results.append({"check": cmd, "ok": False, "detail": f"{type(exc).__name__}"})
            return False, results
        code, out = (res[0], res[1]) if isinstance(res, (tuple, list)) else (res.code, res.stdout_tail)
        results.append({"check": cmd, "ok": code == 0, "detail": (out or "")[-300:] if code else "ok"})
        if code != 0:
            return False, results
    return True, results


def _briefing(job: WorkerJob) -> list[dict[str, Any]]:
    return [{"role": "system", "content": WORKER_SYSTEM},
            {"role": "user", "content": worker_user(job.unit.title or job.unit.id, job.unit.instructions, job.scope,
                                                    job.task, job.strategy, job.guidance, job.map_slice,
                                                    job.criteria_text)}]


async def run_worker(job: WorkerJob) -> WorkerResult:
    """The tool loop of ONE worker variant. Never raises except for cancellation."""
    unit = job.unit
    box = ToolBox(job.ws, job.start_files, job.scope, frozen=job.frozen, allow_tests=job.allow_tests,
                  redactor=job.redactor, isolation=job.isolation)
    messages = _briefing(job)
    tokens0 = job.budget.tokens_used
    steps, nudges, summary, finished, failure = 0, 0, "", False, ""
    own_tokens = 0
    key = f"worker:{unit.id}:{job.variant}:{job.attempt}"
    while steps < job.max_steps:
        reason = job.budget.exhausted()
        if reason:
            failure = reason
            break
        steps += 1
        try:
            reply = await asyncio.wait_for(job.llm.respond(messages, TOOL_SPECS, key=key),
                                           timeout=max(1.0, job.budget.remaining_wall()))
        except asyncio.TimeoutError:
            failure = "model call timed out / wall budget"
            break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = f"model error: {type(exc).__name__}"
            log.warning("worker %s model error: %s", job.agent_id, type(exc).__name__)
            break
        job.budget.add_usage(reply.usage)
        own_tokens += int(reply.usage.get("prompt_tokens", 0)) + int(reply.usage.get("completion_tokens", 0))
        if not reply.tool_calls:
            nudges += 1
            if nudges >= 3:
                failure = "the model stopped calling tools"
                break
            messages += [{"role": "assistant", "content": reply.content or "(empty)"},
                         {"role": "user", "content": "Call exactly one tool now (use `finish` when done)."}]
            continue
        nudges = 0
        calls = reply.tool_calls[:4]
        messages.append({"role": "assistant", "content": reply.content,
                         "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in calls]})
        for call in calls:
            t0 = time.monotonic()
            out = await box.call(call.name, call.args)
            await job.hub.tool(job.agent_id, call.name, out.target, out.ok, int((time.monotonic() - t0) * 1000), out.note)
            messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": out.text[:6000]})
            if out.finished:
                finished, summary = True, out.summary
                break
        if finished:
            break
    if not finished and not failure:
        failure = f"step budget reached ({job.max_steps} steps) without finish"
    changes, dropped = await box.collect_changes()
    notes = [f"dropped out-of-policy changes: {', '.join(dropped[:6])}"] if dropped else []
    result = WorkerResult(unit_id=unit.id, variant=job.variant, ok=False, summary=summary, changes=changes,
                          start_texts={p: job.start_files.get(p) for p in changes}, steps=steps,
                          tokens=own_tokens or (job.budget.tokens_used - tokens0), failure=failure, notes=notes,
                          model=getattr(job.llm, "model", ""))
    if failure:
        return result
    if not changes:
        result.failure = "the worker finished without changing any file"
        return result
    ok, checks = await unit_checks(job.ws, unit, changes)
    result.checks = checks
    result.diff = make_diff({p: job.start_files.get(p) for p in changes}, changes)
    if not ok:
        bad = next((c for c in checks if not c["ok"]), {})
        result.failure = f"unit check failed: {bad.get('check')}: {bad.get('detail', '')}"[:600]
        return result
    result.ok = True
    return result
