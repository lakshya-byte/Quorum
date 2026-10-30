"""Asyncio DAG scheduler: ready units (dependencies satisfied) run in parallel under file-scope locks and a worker cap;
each unit races k worker variants in separate sandbox forks; the first variant whose unit-level checks pass wins and the
others are cancelled (asyncio cancellation; their forks are released). Per-unit retries get the failure notes and the
stronger model. All caps come from Limits (env), never from the model."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app.swarm.budget import Budget
from app.swarm.events import Hub, Redactor
from app.swarm.tools import scopes_overlap
from app.swarm.types import Plan, SwarmCtx, Unit, UnitState, WorkerResult, topo_order
from app.swarm.workers import ChatLLM, WorkerJob, run_worker

log = logging.getLogger(__name__)

STRATEGIES = [
    "Make the smallest correct change that satisfies the unit.",
    "Be defensive: handle edge cases and keep behaviour backward compatible.",
    "Prefer clarity: restructure lightly so the result is easy to review.",
]
UNIT_RETRIES = 1


@dataclass
class Runtime:
    """What every agent of one run shares."""

    ctx: SwarmCtx
    hub: Hub
    budget: Budget
    plan: Plan
    task_type: str
    isolation: str
    redactor: Redactor
    llm_for: Callable[[str, str], ChatLLM]
    frozen: set[str] = field(default_factory=set)
    criteria_text: str = ""
    map_slice: Callable[[Unit], str] = lambda u: ""
    retries: int = UNIT_RETRIES


async def apply_changes(ws: Any, changes: dict[str, str | None]) -> list[str]:
    """Write `changes` into a workspace. Returns the paths that could not be applied (deletions without ws.delete)."""
    skipped: list[str] = []
    for path, text in changes.items():
        if text is None:
            delete = getattr(ws, "delete", None)
            if delete is None:
                skipped.append(path)
            else:
                await delete(path)
        else:
            await ws.write(path, text)
    return skipped


def overlay(files: dict[str, str], changes: dict[str, str | None]) -> dict[str, str]:
    out = dict(files)
    for p, t in changes.items():
        if t is None:
            out.pop(p, None)
        else:
            out[p] = t
    return out


class Scheduler:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.max_units = max(1, min(rt.plan.swarm.max_parallel or 1, rt.budget.limits.max_workers))

    # ---- public --------------------------------------------------------------------------

    async def run(self, units: list[Unit], base_ws: Any, base_files: dict[str, str], round_no: int = 1,
                  guidance: dict[str, str] | None = None) -> dict[str, UnitState]:
        rt = self.rt
        guidance = guidance or {}
        ordered = topo_order(units)
        states = {u.id: UnitState(u) for u in ordered}
        for st in states.values():
            await self._unit_event(st, "pending")
        tasks: dict[asyncio.Task[None], str] = {}
        busy: dict[str, list[str]] = {}
        try:
            while True:
                if not rt.budget.exhausted():
                    for u in ordered:
                        st = states[u.id]
                        if st.status != "pending":
                            continue
                        deps = [states[d] for d in u.depends_on if d in states]
                        if any(d.status in ("failed", "cancelled") for d in deps):
                            st.status = "cancelled"
                            st.failures.append("a dependency did not land")
                            await self._unit_event(st, "cancelled", note="a dependency did not land")
                            continue
                        if not all(d.status == "passed" for d in deps):
                            continue
                        if len(tasks) >= self.max_units:
                            break
                        if any(scopes_overlap(u.scope_files, s) for s in busy.values()):
                            continue
                        st.status = "running"
                        busy[u.id] = list(u.scope_files)
                        task = asyncio.create_task(
                            self._run_unit(st, states, base_ws, base_files, round_no, guidance.get(u.id, "")))
                        tasks[task] = u.id
                if not tasks:
                    left = [s for s in states.values() if s.status == "pending"]
                    if not left:
                        break
                    reason = rt.budget.exhausted() or "unit could not be scheduled"
                    for st in left:
                        st.status = "cancelled"
                        st.failures.append(reason)
                        await self._unit_event(st, "cancelled", note=reason)
                    break
                done, _ = await asyncio.wait(set(tasks), timeout=0.5, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    uid = tasks.pop(t)
                    busy.pop(uid, None)
                    if t.cancelled():
                        continue
                    exc = t.exception()
                    if exc is not None:
                        st = states[uid]
                        st.status = "failed"
                        st.failures.append(f"scheduler error: {type(exc).__name__}")
                        log.warning("unit %s crashed: %s", uid, type(exc).__name__)
                        await self._unit_event(st, "failed", note=st.failures[-1])
        finally:
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        return states

    # ---- one unit ------------------------------------------------------------------------

    def _start_state(self, st: UnitState, states: dict[str, UnitState], base_files: dict[str, str]) -> tuple[
            dict[str, str], dict[str, str | None]]:
        """Starting file state of a unit = base + the changes of its (transitive) dependencies, in dependency order."""
        dep_changes: dict[str, str | None] = {}
        for dep in topo_order([s.unit for s in states.values()]):
            if dep.id in self._deps_of(st.unit, states) and states[dep.id].result:
                dep_changes.update(states[dep.id].result.changes)  # type: ignore[union-attr]
        return overlay(base_files, dep_changes), dep_changes

    @staticmethod
    def _deps_of(unit: Unit, states: dict[str, UnitState]) -> set[str]:
        out: set[str] = set()
        stack = list(unit.depends_on)
        while stack:
            d = stack.pop()
            if d in states and d not in out:
                out.add(d)
                stack.extend(states[d].unit.depends_on)
        return out

    async def _run_unit(self, st: UnitState, states: dict[str, UnitState], base_ws: Any, base_files: dict[str, str],
                        round_no: int, guidance: str) -> None:
        rt, u = self.rt, st.unit
        start_files, dep_changes = self._start_state(st, states, base_files)
        await self._unit_event(st, "running")
        notes: list[str] = []
        for attempt in range(rt.retries + 1):
            if rt.budget.exhausted():
                notes.append(rt.budget.exhausted())
                break
            st.attempts = attempt + 1
            hint = "; ".join(filter(None, [guidance, *notes]))[:1500]
            winner, failures = await self._race(st, attempt, base_ws, start_files, dep_changes, round_no, hint)
            if winner is not None:
                st.result, st.status = winner, "passed"
                await self._unit_event(st, "passed", result=winner)
                return
            st.failures.extend(failures)
            notes = [f"previous attempt failed: {f}" for f in failures[:3]]
        st.status = "failed"
        await self._unit_event(st, "failed", note=(st.failures[-1] if st.failures else "no attempt succeeded"))

    async def _race(self, st: UnitState, attempt: int, base_ws: Any, start_files: dict[str, str],
                    dep_changes: dict[str, str | None], round_no: int, hint: str) -> tuple[WorkerResult | None, list[str]]:
        rt, u = self.rt, st.unit
        k = 1 if attempt else max(1, min(u.variants, rt.budget.limits.max_workers))
        tier = "nano" if attempt == 0 else "super"
        tasks = [asyncio.create_task(self._variant(u, i, attempt, tier, base_ws, start_files, dep_changes, round_no, hint))
                 for i in range(k)]
        winner: WorkerResult | None = None
        failures: list[str] = []
        pending = set(tasks)
        try:
            while pending and winner is None:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t.cancelled():
                        continue
                    exc = t.exception()
                    if exc is not None:
                        failures.append(f"worker crashed: {type(exc).__name__}")
                        continue
                    res: WorkerResult = t.result()
                    if res.ok and winner is None:
                        winner = res
                    elif not res.ok:
                        failures.append(f"variant {res.variant}: {res.failure}")
        finally:
            for t in pending:
                t.cancel()  # first passing variant wins: the rest stop promptly
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        return winner, failures

    async def _variant(self, u: Unit, i: int, attempt: int, tier: str, base_ws: Any, start_files: dict[str, str],
                       dep_changes: dict[str, str | None], round_no: int, hint: str) -> WorkerResult:
        rt = self.rt
        agent_id = f"r{round_no}.{u.id}.v{i}" + (f".a{attempt}" if attempt else "")
        llm = rt.llm_for("worker", tier)
        model = getattr(llm, "model", "")
        iso = rt.isolation
        await rt.hub.agent(agent_id, "worker", "spawned", unit_id=u.id, variant=i, model=model, isolation=iso)
        ws = None
        try:
            async with rt.budget.slot():
                ws = await base_ws.fork()
                await apply_changes(ws, dep_changes)
                await rt.hub.agent(agent_id, "worker", "running", unit_id=u.id, variant=i, model=model, isolation=iso)
                job = WorkerJob(
                    unit=u, variant=i, attempt=attempt, agent_id=agent_id, ws=ws, start_files=start_files,
                    task=rt.ctx.task, strategy=STRATEGIES[i % len(STRATEGIES)], guidance=hint, map_slice=rt.map_slice(u),
                    criteria_text=rt.criteria_text, llm=llm, hub=rt.hub, budget=rt.budget,
                    max_steps=rt.budget.limits.worker_max_steps, scope=list(u.scope_files), frozen=rt.frozen,
                    allow_tests=rt.task_type == "tests", redactor=rt.redactor, isolation=getattr(ws, "isolation", iso))
                result = await run_worker(job)
            await rt.hub.agent(agent_id, "worker", "done" if result.ok else "failed", unit_id=u.id, variant=i,
                               model=model, isolation=iso, summary=result.summary if result.ok else result.failure,
                               tokens=result.tokens, steps=result.steps)
            return result
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await rt.hub.agent(agent_id, "worker", "cancelled", unit_id=u.id, variant=i, model=model, isolation=iso)
            raise
        except Exception as exc:
            log.warning("worker %s crashed: %s", agent_id, type(exc).__name__)
            await rt.hub.agent(agent_id, "worker", "failed", unit_id=u.id, variant=i, model=model, isolation=iso,
                               summary=f"crashed: {type(exc).__name__}")
            return WorkerResult(u.id, i, False, failure=f"worker crashed: {type(exc).__name__}")
        finally:
            if ws is not None:
                with contextlib.suppress(BaseException):
                    await asyncio.shield(ws.release())

    # ---- events --------------------------------------------------------------------------

    async def _unit_event(self, st: UnitState, status: str, *, result: WorkerResult | None = None, note: str = "") -> None:
        data: dict[str, Any] = {"id": st.unit.id, "status": status, "title": st.unit.title,
                                "scope_files": st.unit.scope_files, "depends_on": st.unit.depends_on,
                                "files": sorted(result.changes) if result else []}
        if result:
            data["winner_variant"] = result.variant
            data["diff"] = result.diff
            data["checks"] = result.checks
        if note:
            data["note"] = note[:300]
        await self.rt.hub.emit("unit", data)
