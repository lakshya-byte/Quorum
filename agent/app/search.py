"""Beam search over LLM-proposed fixes, judged only by the tests."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.bugs import Bug
from app.config import BEAM, BRANCH, LOCAL_TEST_TIMEOUT, MAX_DEPTH
from app.proposers import Propose, new_usage
from app.candidate import evaluate_candidate, is_solved, rank
from app.sandbox import Sandbox

log = logging.getLogger(__name__)

Node = dict[str, Any]
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class SearchConfig:
    branch: int = BRANCH
    beam: int = BEAM
    max_depth: int = MAX_DEPTH
    test_timeout: int = LOCAL_TEST_TIMEOUT
    model_override: str | None = None
    model_for: Callable[[int], str] = lambda depth: "fake"
    usage: dict[str, int] = field(default_factory=new_usage)


__all__ = ["SearchConfig", "evaluate", "expand", "is_solved", "rank", "run_search"]


async def evaluate(
    bug: Bug, sandbox: Sandbox, cfg: SearchConfig, *,
    node_id: int, parent: int | None, depth: int, idea: str, code: str, model: str,
) -> Node:
    """Gate, test and scan one candidate (shared pipeline, see app/candidate.py). Node 0 skips the gate."""
    return await evaluate_candidate(
        bug, sandbox, node_id=node_id, parent=parent, depth=depth, idea=idea, code=code, model=model,
        timeout=cfg.test_timeout, skip_policy=node_id == 0,
    )


async def expand(
    bug: Bug, sandbox: Sandbox, propose: Propose, emit: Emit, cfg: SearchConfig,
    parent: Node, i: int, node_id: int,
) -> Node:
    """One job: propose, test, build node, emit. Never raises."""
    depth = parent["depth"] + 1
    model = cfg.model_for(depth)
    try:
        idea, code = await propose(bug, parent, i, cfg.model_override)
        node = await evaluate(
            bug, sandbox, cfg, node_id=node_id, parent=parent["id"], depth=depth,
            idea=idea, code=code, model=model,
        )
    except Exception as exc:
        log.exception("candidate %s failed", node_id)
        node = {
            "id": node_id, "parent": parent["id"], "depth": depth, "idea": "internal error",
            "code": "", "output": f"INTERNAL_ERROR: {type(exc).__name__}: {exc}",
            "passed": 0, "total": 0, "score": 0.0, "model": model, "strategy": "", "latency_ms": 0,
            "tokens": 0, "policy": {"ok": True, "reasons": []}, "security": {"ok": True, "new_findings": []},
        }
    await emit("node", node)
    return node


async def run_search(
    bug: Bug, sandbox: Sandbox, propose: Propose, emit: Emit, cfg: SearchConfig | None = None,
) -> tuple[Node, bool]:
    cfg = cfg or SearchConfig()
    root = await evaluate(
        bug, sandbox, cfg, node_id=0, parent=None, depth=0,
        idea="original buggy code", code=bug["buggy"], model="-",
    )
    await emit("node", root)
    best, frontier, next_id = root, [root], 1

    for depth in range(1, cfg.max_depth + 1):
        if is_solved(best):
            break
        await emit("round", {"depth": depth})
        jobs = [(parent, i) for parent in frontier for i in range(cfg.branch)]
        children = await asyncio.gather(*(
            expand(bug, sandbox, propose, emit, cfg, parent, i, next_id + k)
            for k, (parent, i) in enumerate(jobs)
        ))
        next_id += len(jobs)
        children = sorted(children, key=rank, reverse=True)
        if rank(children[0]) > rank(best):
            best = children[0]
        frontier = children[: cfg.beam]

    solved = is_solved(best)
    await emit("done", {"solved": solved, "best": best, "usage": dict(cfg.usage), "engine": "loop"})
    return best, solved
