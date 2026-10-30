"""Critic: reads the failed hard-gate results and writes targeted repair units for the next round. The units are
re-validated in code (existing non-test source files only), and a deterministic repair unit is used if the model
fails, so a failed gate always leads to a concrete next step while rounds remain."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.repo_detect import is_test_path
from app.swarm.planner import LLMJsonError, json_call
from app.swarm.prompts import CRITIC_SYSTEM, untrusted
from app.swarm.scheduler import Runtime
from app.swarm.types import Unit, VerifyRow, slug

log = logging.getLogger(__name__)

MAX_REPAIR_UNITS = 4


class RepairUnit(BaseModel):
    id: str = "fix"
    title: str = ""
    scope_files: list[str] = Field(default_factory=list)
    instructions: str = ""
    criterion_ids: list[str] = Field(default_factory=list)


class CriticOut(BaseModel):
    lesson: str = ""
    units: list[RepairUnit] = Field(default_factory=list)


def failure_text(rows: list[VerifyRow]) -> str:
    return "\n".join(f"- {r.criterion_id} ({r.kind}): {r.detail[:400]}" for r in rows)


async def critique(rt: Runtime, failing: list[VerifyRow], files: dict[str, str], changed: list[str], round_no: int,
                   frozen: set[str]) -> tuple[str, list[Unit]]:
    """(lesson, repair units) for round `round_no + 1`."""
    llm = rt.llm_for("critic", "super")
    agent_id = f"r{round_no}.critic"
    model = getattr(llm, "model", "")
    await rt.hub.agent(agent_id, "critic", "spawned", model=model, isolation=rt.isolation)
    await rt.hub.agent(agent_id, "critic", "running", model=model, isolation=rt.isolation)
    fails = failure_text(failing)
    editable = [p for p in sorted(files) if not is_test_path(p) and p not in frozen]
    out: CriticOut | None = None
    try:
        user = (f"Task:\n{untrusted(rt.ctx.task)}\n\nFailed hard checks:\n{untrusted(fails)}\n\n"
                f"Files changed so far: {changed[:40]}\nExisting source files (scope must come from these): "
                f"{editable[:200]}")
        parsed = await asyncio.wait_for(
            json_call(llm, CRITIC_SYSTEM, user, CriticOut, key=f"critic:{round_no}", budget=rt.budget, tries=2),
            timeout=max(1.0, rt.budget.remaining_wall()))
        assert isinstance(parsed, CriticOut)
        out = parsed
    except asyncio.CancelledError:
        raise
    except (LLMJsonError, asyncio.TimeoutError) as exc:
        log.warning("critic fell back to a deterministic repair unit: %s", type(exc).__name__)
    units: list[Unit] = []
    for i, ru in enumerate((out.units if out else [])[:MAX_REPAIR_UNITS], 1):
        scope = [p for p in dict.fromkeys(ru.scope_files) if p in files and not is_test_path(p) and p not in frozen]
        if not scope:
            continue
        units.append(Unit(id=slug(f"r{round_no + 1}-{ru.id}", f"r{round_no + 1}-fix{i}"), title=(ru.title or "Repair")[:120],
                          scope_files=scope[:10], variants=1,
                          instructions=f"{ru.instructions[:1200]}\n\nFailing checks to fix:\n{fails}"[:2800]))
    if not units:
        scope = [p for p in changed if p in files and not is_test_path(p) and p not in frozen][:8] or editable[:5]
        units = [Unit(id=f"r{round_no + 1}-fix", title="Repair failing checks", scope_files=scope, variants=1,
                      instructions=f"Make the failing hard checks pass without weakening tests.\n\n{fails}"[:2800])]
    lesson = (out.lesson if out and out.lesson else "repair the failing hard checks")[:300]
    await rt.hub.agent(agent_id, "critic", "done", model=model, isolation=rt.isolation, summary=lesson)
    return lesson, units
