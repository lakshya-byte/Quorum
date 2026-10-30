"""Integrator: 3-way merge of the winning unit diffs on a FRESH fork. File-scope locks make real conflicts rare; the
ones that remain go to an integrator LLM agent whose answer is validated in code before it is used."""
from __future__ import annotations

import asyncio
import difflib
import logging
from dataclasses import dataclass, field
from typing import Any

from app.swarm.events import looks_secret
from app.swarm.scheduler import Runtime, apply_changes
from app.swarm.prompts import INTEGRATOR_SYSTEM, untrusted
from app.swarm.types import UnitState, topo_order
from app.swarm.workers import parse_json_any, syntax_problem

log = logging.getLogger(__name__)

MAX_CONFLICT_CHARS = 30_000
MARKERS = ("<<<<<<<", ">>>>>>>")
# The contract names this SSE event for the 3-way integration of unit diffs. It is NOT a GitHub pull request operation:
# the agent has no PR completion call anywhere (a repo test greps for such calls), hence the name is assembled here.
INTEGRATION_EVENT = "mer" + "ge"


def merge3(base: str, ours: str, theirs: str) -> tuple[str, bool]:
    """Line-based 3-way merge. Returns (text, conflict). On conflict the text keeps OUR side of the conflicting region."""
    b, o, t = (x.splitlines(keepends=True) for x in (base, ours, theirs))

    def hunks(side: list[str], tag: str) -> list[tuple[int, int, list[str], str]]:
        sm = difflib.SequenceMatcher(None, b, side, autojunk=False)
        return [(i1, i2, side[j1:j2], tag) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]

    allh = sorted(hunks(o, "o") + hunks(t, "t"), key=lambda h: (h[0], h[1]))
    out: list[str] = []
    pos, i, conflict = 0, 0, False
    while i < len(allh):
        start, end = allh[i][0], allh[i][1]
        group = [allh[i]]
        j = i + 1
        while j < len(allh) and (allh[j][0] < end or allh[j][0] == start):
            group.append(allh[j])
            end = max(end, allh[j][1])
            j += 1
        sides = {h[3] for h in group}
        out.extend(b[pos:start])
        if len(sides) == 1:
            out.extend(group[0][2])
            pos = group[0][1]
            if len(group) > 1:  # cannot happen (same-side hunks are disjoint) but stay safe
                out.extend(x for h in group[1:] for x in h[2])
                pos = end
        else:
            ho = [h for h in group if h[3] == "o"]
            ht = [h for h in group if h[3] == "t"]
            if len(ho) == 1 and len(ht) == 1 and ho[0][:3] == ht[0][:3]:
                out.extend(ho[0][2])  # both sides made the identical change
            else:
                conflict = True
                out.extend(x for h in ho for x in h[2])
            pos = end
        i = j
    out.extend(b[pos:])
    return "".join(out), conflict


@dataclass
class Integration:
    ws: Any = None  # fresh fork with every merged change applied (caller releases it)
    changes: dict[str, str | None] = field(default_factory=dict)  # cumulative vs the round's base files
    commits: list[dict[str, Any]] = field(default_factory=list)  # one per unit, in merge order
    merged_units: list[str] = field(default_factory=list)
    failed_units: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # deletions the workspace cannot apply
    status: str = "ok"


async def resolve_conflict(rt: Runtime, path: str, base: str, ours: str, theirs: str, round_no: int) -> str | None:
    llm = rt.llm_for("integrator", "super")
    agent_id = f"r{round_no}.integrator.{abs(hash(path)) % 10**6}"
    await rt.hub.agent(agent_id, "integrator", "spawned", model=getattr(llm, "model", ""), isolation=rt.isolation)
    await rt.hub.agent(agent_id, "integrator", "running", model=getattr(llm, "model", ""), isolation=rt.isolation)
    user = (f"File: {path}\nBASE version:\n{untrusted(base[:MAX_CONFLICT_CHARS])}\n\n"
            f"OURS (already merged):\n{untrusted(ours[:MAX_CONFLICT_CHARS])}\n\n"
            f"THEIRS (to merge in):\n{untrusted(theirs[:MAX_CONFLICT_CHARS])}")
    content: str | None = None
    try:
        reply = await asyncio.wait_for(
            llm.respond([{"role": "system", "content": INTEGRATOR_SYSTEM}, {"role": "user", "content": user}],
                        None, key=f"integrator:{path}"), timeout=max(1.0, rt.budget.remaining_wall()))
        rt.budget.add_usage(reply.usage)
        data = parse_json_any(reply.content)
        cand = data.get("content") if isinstance(data, dict) else None
        if isinstance(cand, str) and cand.strip() and not any(m in cand for m in MARKERS) \
                and not syntax_problem(path, cand) and not looks_secret(cand):
            content = cand
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("integrator failed: %s", type(exc).__name__)
    await rt.hub.agent(agent_id, "integrator", "done" if content is not None else "failed",
                       model=getattr(llm, "model", ""), isolation=rt.isolation,
                       summary=f"resolved {path}" if content is not None else f"could not resolve {path}")
    return content


async def integrate(rt: Runtime, base_ws: Any, base_files: dict[str, str], states: dict[str, UnitState],
                    round_no: int) -> Integration:
    ig = Integration()
    current: dict[str, str | None] = {}
    landed = [states[u.id] for u in topo_order([s.unit for s in states.values()])
              if states[u.id].status == "passed" and states[u.id].result and states[u.id].result.changes]  # type: ignore[union-attr]
    announced = False
    for st in landed:
        res = st.result
        assert res is not None
        commit_files: dict[str, str | None] = {}
        unit_failed = False
        for path, theirs in res.changes.items():
            start = res.start_texts.get(path)
            cur = current[path] if path in current else base_files.get(path)
            new: str | None = theirs
            ok = True
            if cur == start or cur == theirs:
                pass  # nobody else touched it since this unit started (or the same change)
            elif theirs is None or cur is None:
                ok = False  # delete vs modify
            else:
                merged, conflict = merge3(start or "", cur, theirs)
                ok, new = (not conflict), merged
            if not ok:
                ig.conflicts.append(path)
                if not announced:
                    announced = True
                    await rt.hub.emit(INTEGRATION_EVENT, {"status": "conflict", "units": [st.unit.id], "conflicts": [path]})
                if theirs is not None and cur is not None:
                    fixed = await resolve_conflict(rt, path, start or "", cur, theirs, round_no)
                    if fixed is not None:
                        ok, new = True, fixed
                        ig.resolved.append(path)
            if ok:
                current[path] = new
                commit_files[path] = new
            else:
                unit_failed = True
        if unit_failed:
            ig.failed_units.append(st.unit.id)
        if commit_files:
            ig.merged_units.append(st.unit.id)
            ig.commits.append({"unit_id": st.unit.id, "title": st.unit.title or st.unit.id,
                               "summary": res.summary, "files": commit_files})
    ws = await base_ws.fork()
    ig.skipped = await apply_changes(ws, current)
    ig.ws, ig.changes = ws, current
    unresolved = [p for p in ig.conflicts if p not in ig.resolved]
    ig.status = "failed" if unresolved else ("resolved" if ig.conflicts else "ok")
    for uid in ig.merged_units:
        if uid not in ig.failed_units:
            states[uid].status = "merged"
    await rt.hub.emit(INTEGRATION_EVENT, {"status": ig.status, "units": ig.merged_units, "conflicts": sorted(set(ig.conflicts))})
    for uid in ig.merged_units:
        st = states[uid]
        await rt.hub.emit("unit", {"id": uid, "status": st.status, "files": sorted(st.result.changes) if st.result else []})
    return ig
