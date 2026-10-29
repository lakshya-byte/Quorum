"""LangGraph team engine (engine="graph").

    START ─┬─ input_guard ─┐
           ├─ triage ──────┼─> plan_round ──Send×3──> propose ──> select ─┬─ solved ──────> finish
           └─ baseline ────┘       ^                                       ├─ rounds left ─> critic (Send per survivor)
                                   └───────────────────────────────────────┴───────────────────┘
                                                                           └─ out of rounds ─> finish

- input_guard, triage and the baseline test of the original code run concurrently.
- One proposer per triage strategy via LangGraph's Send; round 1 uses Nano, later rounds Super.
- Each candidate is gated and tested the moment it arrives: policy -> sandbox -> security -> score -> node event.
- Early exit: the first candidate that passes every test and the gate sets the round's `solved` event;
  every in-flight sibling (LLM call or sandbox run) is cancelled.
- select keeps the top 2 (tests decide; ties -> smaller diff). The critic (Super) runs only for survivors,
  in parallel, and its one-line lesson feeds the next round. Skipped if a single survivor already scores 1.0.
- finish emits `done` first; the reviewer (Super) then writes the PR draft off the critical path, and the
  output guard checks that text.
"""
from __future__ import annotations

import asyncio
import logging
import operator
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Awaitable, Callable, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.bugs import Bug
from app.candidate import evaluate_candidate, is_solved, rank
from app.config import Settings
from app.sandbox import Sandbox
from app.telemetry import span

log = logging.getLogger(__name__)

Node = dict[str, Any]
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
TOP_K = 2
SLOTS = 3


class BudgetExceeded(RuntimeError):
    pass


class Cancelled(Exception):
    pass


@dataclass
class GraphCtx:
    """Per-run, non-serialisable dependencies (passed via config['configurable']['ctx'])."""

    run_id: str
    bug: Bug
    mode: str
    settings: Settings
    sandbox: Sandbox
    team: Any
    guard: Any
    emit: Emit
    test_timeout: int = 20
    usage: dict[str, int] = field(default_factory=lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
    next_id: int = 1
    candidates_started: int = 0
    cancelled: int = 0
    round_solved: asyncio.Event = field(default_factory=asyncio.Event)
    pr_draft: dict[str, Any] | None = None
    started: float = field(default_factory=time.monotonic)
    trace_tags: list[str] = field(default_factory=list)

    def add_usage(self, used: dict[str, int]) -> None:
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += used.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += used.get("completion_tokens", 0)

    @property
    def tokens(self) -> int:
        return self.usage["prompt_tokens"] + self.usage["completion_tokens"]

    def take_id(self) -> int:
        nid = self.next_id
        self.next_id += 1
        return nid


class TeamState(TypedDict, total=False):
    round: int
    input_ok: bool
    input_reasons: list[str]
    cause: str
    strategies: list[str]
    candidates: Annotated[list[Node], operator.add]
    lessons: Annotated[list[dict[str, Any]], operator.add]
    survivors: list[Node]
    solved: bool


def _ctx(config: RunnableConfig) -> GraphCtx:
    return config["configurable"]["ctx"]  # type: ignore[index]


async def _race(coro: Awaitable[Any], stop: asyncio.Event) -> Any:
    """Run `coro` unless `stop` fires first; then cancel it (LLM call or sandbox run) and raise Cancelled."""
    task = asyncio.ensure_future(coro)
    waiter = asyncio.ensure_future(stop.wait())
    try:
        done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return task.result()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        raise Cancelled()
    finally:
        waiter.cancel()
        if not task.done():
            task.cancel()


# ---- nodes -------------------------------------------------------------------------

async def input_guard(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    with span("graph.input_guard", group="PatchLoop/Graph"):
        text = f"{ctx.bug['issue']}\n\n{ctx.bug['buggy']}"
        event = await ctx.guard.check("input", text, ctx.mode, ctx.run_id)
    await ctx.emit("guard", event)
    return {"input_ok": event["verdict"] == "pass", "input_reasons": event["reasons"]}


async def triage(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    with span("graph.triage", group="PatchLoop/Graph"):
        out, used = await ctx.team.triage(ctx.bug, config, ctx.run_id)
    ctx.add_usage(used)
    await ctx.emit("triage", {"cause": out.cause, "strategies": out.strategies})
    return {"cause": out.cause, "strategies": out.strategies}


async def baseline(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    with span("graph.baseline", group="PatchLoop/Graph"):
        root = await evaluate_candidate(
            ctx.bug, ctx.sandbox, node_id=0, parent=None, depth=0, idea="original buggy code",
            code=ctx.bug["buggy"], model="-", strategy="", timeout=ctx.test_timeout, skip_policy=True,
        )
    await ctx.emit("node", root)
    return {"candidates": [root]}


async def plan_round(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    if not state.get("input_ok", True):
        return {}
    nxt = state.get("round", 0) + 1
    ctx.round_solved = asyncio.Event()
    await ctx.emit("round", {"depth": nxt})
    return {"round": nxt}


def route_proposers(state: TeamState) -> list[Send] | str:
    if not state.get("input_ok", True):
        return "finish"
    rnd = state["round"]
    survivors = state.get("survivors") or [c for c in state["candidates"] if c["id"] == 0]
    lessons = {l["node_id"]: l["lesson"] for l in state.get("lessons", []) if l["round"] == rnd - 1}
    strategies = state.get("strategies") or []
    sends = []
    for slot in range(SLOTS):
        parent = survivors[slot % len(survivors)]
        sends.append(Send("propose", {
            "slot": slot, "round": rnd, "parent": parent, "cause": state.get("cause", ""),
            "strategy": strategies[slot % len(strategies)] if strategies else "",
            "lesson": lessons.get(parent["id"], ""),
        }))
    return sends


async def propose(payload: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    s = ctx.settings
    if ctx.candidates_started >= s.run_max_candidates:
        raise BudgetExceeded(f"candidate budget exhausted ({s.run_max_candidates})")
    if ctx.tokens >= s.run_max_tokens:
        raise BudgetExceeded(f"token budget exhausted ({ctx.tokens} >= {s.run_max_tokens})")
    ctx.candidates_started += 1
    stop = ctx.round_solved
    t0 = time.monotonic()
    rnd, parent = payload["round"], payload["parent"]
    try:
        with span("graph.propose", group="PatchLoop/Graph"):
            proposal = await _race(ctx.team.propose(
                ctx.bug, payload["strategy"], parent, payload["lesson"], payload["cause"],
                rnd, payload["slot"], config, ctx.run_id), stop)
        ctx.add_usage(proposal.usage)
        node_id = ctx.take_id()
        with span("graph.evaluate", group="PatchLoop/Graph"):
            node = await _race(evaluate_candidate(
                ctx.bug, ctx.sandbox, node_id=node_id, parent=parent["id"], depth=rnd, idea=proposal.idea,
                code=proposal.code, model=proposal.model, strategy=payload["strategy"],
                extra_files=proposal.extra_files, timeout=ctx.test_timeout, max_diff_lines=s.max_diff_lines,
                started=t0, tokens=proposal.usage["prompt_tokens"] + proposal.usage["completion_tokens"],
            ), stop)
    except Cancelled:
        ctx.cancelled += 1
        log.info("early exit cancelled round %s slot %s", rnd, payload["slot"])
        return {"candidates": []}
    except BudgetExceeded:
        raise
    except Exception as exc:  # one broken candidate must not kill the team
        log.exception("candidate failed")
        node = {
            "id": ctx.take_id(), "parent": parent["id"], "depth": rnd, "idea": "internal error",
            "strategy": payload["strategy"], "code": "", "output": f"INTERNAL_ERROR: {type(exc).__name__}: {exc}",
            "passed": 0, "total": 0, "score": 0.0, "model": "-", "latency_ms": int((time.monotonic() - t0) * 1000),
            "tokens": 0, "policy": {"ok": True, "reasons": []}, "security": {"ok": True, "new_findings": []},
        }
    if stop.is_set() and not is_solved(node):
        ctx.cancelled += 1  # finished after the winner: drop it, the round is over
        return {"candidates": []}
    await ctx.emit("node", node)
    if is_solved(node):
        stop.set()  # EARLY EXIT: cancel every in-flight sibling
    return {"candidates": [node]}


async def select(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
    rnd = state["round"]
    this_round = [c for c in state["candidates"] if c["depth"] == rnd]
    ranked = sorted(this_round, key=rank, reverse=True)
    survivors = ranked[:TOP_K] or state.get("survivors") or []
    return {"survivors": survivors, "solved": any(is_solved(c) for c in this_round)}


def route_after_select(state: TeamState, config: RunnableConfig) -> list[Send] | str:
    ctx = _ctx(config)
    if state.get("solved") or state["round"] >= ctx.settings.max_rounds:
        return "finish"
    survivors = state.get("survivors") or []
    if not survivors:
        return "plan_round"
    if len(survivors) == 1 and survivors[0]["score"] >= 1.0:
        return "plan_round"  # nothing to learn from a perfect single survivor
    return [Send("critic", {"node": n, "round": state["round"]}) for n in survivors]


async def critic(payload: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    node = payload["node"]
    if ctx.tokens >= ctx.settings.run_max_tokens:
        raise BudgetExceeded(f"token budget exhausted ({ctx.tokens} >= {ctx.settings.run_max_tokens})")
    with span("graph.critic", group="PatchLoop/Graph"):
        lesson, used, model = await ctx.team.critic(ctx.bug, node, config, ctx.run_id)
    ctx.add_usage(used)
    await ctx.emit("critic", {"node_id": node["id"], "lesson": lesson, "model": model})
    return {"lessons": [{"round": payload["round"], "node_id": node["id"], "lesson": lesson}]}


def best_of(candidates: list[Node]) -> Node:
    return max(candidates, key=rank)


async def finish(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    candidates = state.get("candidates", [])
    best = best_of(candidates)
    solved = is_solved(best)
    if not state.get("input_ok", True):
        await ctx.emit("error", {"stage": "input_guard",
                                 "message": "input blocked by guardrails: " + "; ".join(state.get("input_reasons", []))})
    await ctx.emit("done", {
        "solved": solved, "best": best, "usage": dict(ctx.usage), "engine": "graph",
        "rounds": state.get("round", 0), "candidates": len(candidates) - 1, "cancelled": ctx.cancelled,
    })
    if solved:  # off the critical path: done is already on the wire
        await write_review(ctx, best, config)
    return {}


async def write_review(ctx: GraphCtx, best: Node, config: RunnableConfig | None) -> None:
    try:
        with span("graph.reviewer", group="PatchLoop/Graph"):
            review, used, model = await ctx.team.review(ctx.bug, best, getattr(ctx.sandbox, "label", "a sandbox"),
                                                        config, ctx.run_id)
        ctx.add_usage(used)
        text = f"{review.title}\n\n{review.body}\n\nRisk: {review.risk}"
        event = await ctx.guard.check("output", text, ctx.mode, ctx.run_id)
        await ctx.emit("guard", event)
        ctx.pr_draft = {"title": review.title, "body": review.body, "risk": review.risk, "model": model,
                        "guard": event["verdict"]}
    except Exception as exc:
        log.warning("reviewer failed (%s); PR will use the template body", type(exc).__name__)


def build_graph() -> Any:
    g = StateGraph(TeamState)
    g.add_node("input_guard", input_guard)
    g.add_node("triage", triage)
    g.add_node("baseline", baseline)
    g.add_node("plan_round", plan_round)
    g.add_node("propose", propose)
    g.add_node("select", select)
    g.add_node("critic", critic)
    g.add_node("finish", finish)
    g.add_edge(START, "input_guard")
    g.add_edge(START, "triage")
    g.add_edge(START, "baseline")
    g.add_edge(["input_guard", "triage", "baseline"], "plan_round")
    g.add_conditional_edges("plan_round", route_proposers, ["propose", "finish"])
    g.add_edge("propose", "select")
    g.add_conditional_edges("select", route_after_select, ["critic", "plan_round", "finish"])
    g.add_edge("critic", "plan_round")
    g.add_edge("finish", END)
    return g.compile()


_GRAPH: Any = None


def graph() -> Any:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


async def run_graph(ctx: GraphCtx) -> Node | None:
    """Run the team. Budgets: wall time here, tokens/candidates inside nodes. Returns the best node."""
    s = ctx.settings
    tags = [f"run_id:{ctx.run_id}", f"bug_id:{ctx.bug['id']}", "engine:graph", f"mode:{ctx.mode}"]
    config: RunnableConfig = {
        "configurable": {"ctx": ctx}, "recursion_limit": 25 + 8 * s.max_rounds, "run_name": "patchloop-team",
        "tags": tags + ctx.trace_tags,
        "metadata": {"run_id": ctx.run_id, "bug_id": ctx.bug["id"], "engine": "graph", "mode": ctx.mode},
    }
    seen: list[Node] = []
    real_emit = ctx.emit

    async def tracking_emit(kind: str, data: dict[str, Any]) -> None:
        if kind == "node":
            seen.append(data)
        await real_emit(kind, data)

    ctx.emit = tracking_emit
    try:
        async with asyncio.timeout(s.run_max_seconds):
            await graph().ainvoke({"round": 0, "candidates": [], "lessons": []}, config=config)
    except (BudgetExceeded, TimeoutError) as exc:
        reason = str(exc) if isinstance(exc, BudgetExceeded) else f"wall-time budget exhausted ({s.run_max_seconds}s)"
        await real_emit("error", {"stage": "budget", "message": reason})
        if seen:
            best = best_of(seen)
            await real_emit("done", {"solved": is_solved(best), "best": best, "usage": dict(ctx.usage),
                                     "engine": "graph", "candidates": len(seen) - 1, "cancelled": ctx.cancelled,
                                     "stopped": "budget"})
        raise BudgetExceeded(reason) from None
    finally:
        ctx.emit = real_emit
    return best_of(seen) if seen else None
