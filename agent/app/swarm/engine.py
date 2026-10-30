"""The swarm engine (LangGraph): prepare -> spec -> round (scheduler) -> integrate+verify -> [critic -> round]* -> finish.

    START -> prepare -+-> spec -> round -> verify -+-> finish -> END
                      |                    ^      |
                      +-> finish (clarify) |      +-> critic -> round
                                           +-------------------+

LLMs write plans, code and verifiers; PLAIN CODE decides: the outcome comes from deterministic verifier results
(`compute_outcome`), never from a model's opinion. See docs/CONTRACT-V3-SWARM.md.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.policy import ast_violations, path_violation
from app.repo_detect import is_test_path
from app.swarm.budget import Budget, Limits, budget_ticker, resolve_limits
from app.swarm.critic import critique
from app.swarm.deps import SwarmDepsError
from app.swarm.events import Hub, Redactor, looks_secret
from app.swarm.integrator import Integration, integrate
from app.swarm.planner import (DESCRIPTIONS, MANDATORY_HARD, TASK_VERIFIER_KINDS, TYPE_REQUIRED, digest, has_task_verifier,
                               make_plan, plan_event, synthesize_verifiers)
from app.swarm.scheduler import Runtime, Scheduler, overlay
from app.swarm.tools import MAX_FILES_PER_RUN, list_symbols
from app.swarm.types import ADVISORY_KINDS, CriterionSpec, Plan, SwarmCtx, Unit, UnitState, VerifyRow
from app.swarm.workers import ChatLLM, LiveLLM, make_diff

log = logging.getLogger(__name__)

PRECHECK_TYPES = ("policy", "secrets")


# ---- LLM factory for live runs ------------------------------------------------------------------------

def live_llm_factory(ctx: SwarmCtx) -> Callable[[str, str], ChatLLM]:
    """(role, tier) -> LiveLLM. Planner/spec/critic/integrator use Super; workers Nano first, Super on retry."""
    s = ctx.settings
    cache: dict[tuple[str, str], ChatLLM] = {}

    def config_factory(key: str) -> dict[str, Any]:
        return {"tags": [*ctx.trace_tags, f"agent:{key.split(':')[0]}"], "metadata": {**ctx.trace_meta, "agent_key": key}}

    def factory(role: str, tier: str) -> ChatLLM:
        tier = "super" if role in ("planner", "spec", "critic", "integrator") else tier
        key = (role, tier)
        if key not in cache:
            model = (s.model_super or s.model_nano) if tier == "super" else (s.model_nano or s.model_super)
            cache[key] = LiveLLM(s, model, temperature=0.2 if role != "worker" else 0.3, tool_mode=s.swarm_tool_mode,
                                 config_factory=config_factory)
        return cache[key]

    return factory


# ---- deterministic gates and outcome ----------------------------------------------------------------------

def local_policy(changes: dict[str, str | None], original: dict[str, str], task_type: str, isolation: str) -> tuple[bool, str]:
    """The path/policy gate computed by plain code over the swarm's cumulative changes (independent of the verifier)."""
    reasons: list[str] = []
    if len(changes) > MAX_FILES_PER_RUN:
        reasons.append(f"too many files changed: {len(changes)} > {MAX_FILES_PER_RUN}")
    for path, text in changes.items():
        bad = path_violation(path)
        if bad:
            reasons.append(bad)
        elif is_test_path(path) and task_type != "tests":
            reasons.append(f"{path}: test file {'edited' if path in original else 'added'} outside a tests task")
        elif text is None and is_test_path(path):
            reasons.append(f"{path}: test deleted")
        elif text is not None and isolation == "local" and path.endswith(".py"):
            reasons.extend(f"{path}: {v}" for v in ast_violations(text)[:2])
    return (not reasons), ("; ".join(reasons[:4]) or f"{len(changes)} file(s) pass the path policy")


def local_secrets(changes: dict[str, str | None]) -> tuple[bool, str]:
    hits = [f"{p}: {looks_secret(t)[0]}" for p, t in changes.items() if t and looks_secret(t)]
    return (not hits), ("; ".join(hits[:3]) or "no secret-looking strings added")


def hard_ok(r: VerifyRow) -> bool:
    return r.status in ("pass", "skip")


def compute_outcome(*, rows: list[VerifyRow], plan: Plan, units_total: int, units_landed: int, changed: bool,
                    needs_input: bool = False, blocked: bool = False) -> tuple[str, list[str]]:
    """(outcome, reasons) per contract section 1. Pure function of verifier results and plan facts."""
    if needs_input:
        return "needs_input", ["the planner needs a clarification"]
    if blocked:
        return "blocked", ["guard or policy blocked the run"]
    hard = [r for r in rows if r.hard]
    if not hard or any(not hard_ok(r) for r in hard):
        return "failed", [f"hard gate failed: {r.criterion_id}" for r in hard if not hard_ok(r)] or ["no verification ran"]
    if not changed:
        return "failed", ["no file was changed"]
    reasons: list[str] = []
    if units_landed < units_total:
        reasons.append(f"only {units_landed} of {units_total} planned units landed")
    for c in plan.criteria:
        if c.downgraded and c.user_stated:
            reasons.append(f"criterion {c.id} had no executable verifier ({c.downgraded[:100]})")
        elif c.downgraded:
            reasons.append(f"criterion {c.id} was downgraded to advisory")
    needed = set(TYPE_REQUIRED.get(plan.task_type, ())) or set(TASK_VERIFIER_KINDS)
    for r in hard:
        if r.status == "skip" and r.kind not in MANDATORY_HARD and r.kind in needed | TASK_VERIFIER_KINDS:
            reasons.append(f"{r.criterion_id} was skipped, so it did not verify anything ({r.detail[:80]})")
    if not has_task_verifier(plan):
        reasons.append("no executable task-specific verifier exists; only the baseline gates ran")
    return ("partial", reasons) if reasons else ("complete", [])


# ---- run state ------------------------------------------------------------------------------------------

class GState(TypedDict, total=False):
    route: str


@dataclass
class RunState:
    ctx: SwarmCtx
    hub: Hub
    budget: Budget
    limits: Limits
    llm_for: Callable[[str, str], ChatLLM]
    deps: Any
    store: Any = None
    plan: Plan | None = None
    repo_map: Any = None
    baseline: Any = None
    orig_ws: Any = None
    base_ws: Any = None
    cur_ws: Any = None
    isolation: str = "local"
    spec_files: dict[str, str] = field(default_factory=dict)
    frozen: set[str] = field(default_factory=set)
    base_files: dict[str, str] = field(default_factory=dict)  # original + verification assets
    round_base_files: dict[str, str] = field(default_factory=dict)
    changes: dict[str, str | None] = field(default_factory=dict)  # cumulative worker changes vs base_files
    commits: list[dict[str, Any]] = field(default_factory=list)
    all_states: dict[str, UnitState] = field(default_factory=dict)
    first_round_ids: list[str] = field(default_factory=list)
    pending_units: list[Unit] = field(default_factory=list)
    guidance: dict[str, str] = field(default_factory=dict)
    rows: list[VerifyRow] = field(default_factory=list)
    round: int = 0
    stop: str = ""  # needs_input | blocked | budget | error
    stopped_reason: str = ""
    rt: Runtime | None = None
    emitted_artifacts: set[str] = field(default_factory=set)
    owned_ws: list[Any] = field(default_factory=list)
    last_integration: Integration | None = None
    skipped_deletes: list[str] = field(default_factory=list)
    last_states: dict[str, UnitState] = field(default_factory=dict)

    # -- helpers
    async def flush_artifacts(self) -> None:
        if self.store is None:
            return
        try:
            items = list(self.store.list())
        except Exception:
            return
        for a in items:
            aid = str(getattr(a, "id", ""))
            if not aid or aid in self.emitted_artifacts:
                continue
            self.emitted_artifacts.add(aid)
            await self.hub.emit("artifact", {
                "id": aid, "kind": getattr(a, "kind", "log"), "label": str(getattr(a, "label", ""))[:120],
                "phase": getattr(a, "phase", "n/a") or "n/a", "viewport": getattr(a, "viewport", None),
                "mime": getattr(a, "mime", "text/plain")})

    def criteria_text(self) -> str:
        assert self.plan
        return "\n".join(f"- {'HARD' if c.hard else 'advisory'} {c.kind}: {c.description or DESCRIPTIONS.get(c.kind, '')}"
                         for c in self.plan.criteria)

    def map_slice(self, unit: Unit) -> str:
        lines = []
        for p in unit.scope_files[:8]:
            text = self.base_files.get(p)
            if text is not None:
                syms = ", ".join(n for _, n in list_symbols(text, 12))
                lines.append(f"- {p} ({len(text)}b): {syms}")
        tests = [p for p in sorted(self.base_files) if is_test_path(p)][:12]
        if tests:
            lines.append("tests (read-only, run them): " + ", ".join(tests))
        if self.frozen:
            lines.append("verification files (read-only): " + ", ".join(sorted(self.frozen)[:10]))
        return "\n".join(lines)[:3000] or "(new files only)"

    async def emit_status(self, stage: str, message: str) -> None:
        await self.hub.emit("status", {"stage": stage, "message": message})

    # -- stages
    async def prepare(self) -> None:
        ctx, d = self.ctx, self.deps
        await self.emit_status("sandbox", "opening sandbox and mapping the repository")
        self.orig_ws = await d.workspace_factory.open(ctx.files, language_hint=ctx.language)
        self.isolation = getattr(self.orig_ws, "isolation", "local")
        self.store = d.new_store()
        ctx.result["artifact_store"] = self.store
        self.repo_map = await asyncio.to_thread(d.build_repo_map, ctx.files)

        async def baseline() -> Any:
            # on the ORIGINAL workspace itself: dependency installs done here are inherited by every later fork
            try:
                return await d.baseline(self.orig_ws, self.repo_map, self.store)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("baseline failed: %s", type(exc).__name__)
                return None

        async def plan() -> Plan:
            if ctx.plan is not None:
                return ctx.plan
            return await make_plan(ctx, self.llm_for("planner", "super"), self.budget, self.limits, self.repo_map)

        self.baseline, self.plan = await asyncio.gather(baseline(), plan())
        await self.flush_artifacts()
        assert self.plan
        if self.baseline is None:
            self.plan.notes.append("baseline could not be collected: relative regression checks may be unreliable")
        ctx.trace_meta["task_type"] = self.plan.task_type
        if self.plan.clarify and not ctx.answers:
            await self.hub.emit("clarify", {"questions": [{"id": q.id, "text": q.text} for q in self.plan.clarify]})
            self.stop = "needs_input"
            return
        await self.hub.emit("plan", plan_event(self.plan))
        scope = list(dict.fromkeys(f for u in self.plan.units for f in u.scope_files if not f.endswith("/")))
        await self.hub.emit("locate", {"files": [{"path": p, "reason": "in a planned unit's scope"} for p in scope[:20]]})
        self.rt = Runtime(ctx=ctx, hub=self.hub, budget=self.budget, plan=self.plan, task_type=self.plan.task_type,
                          isolation=self.isolation, redactor=self.hub.red, llm_for=self.llm_for,
                          criteria_text=self.criteria_text(), map_slice=self.map_slice)

    async def spec(self) -> None:
        assert self.plan and self.rt
        ctx = self.ctx
        context = digest(ctx.files, self.repo_map, 9000)
        self.frozen = await synthesize_verifiers(ctx, self.plan, self.orig_ws, self.baseline, self.store, self.hub,
                                                 self.budget, self.llm_for, context, self.isolation)
        await self.flush_artifacts()
        for c in self.plan.criteria:
            for path, text in (c.params.get("files") or {}).items():
                self.spec_files[path] = text
        self.base_files = overlay(ctx.files, dict(self.spec_files))
        self.base_ws = await self.orig_ws.fork()
        self.owned_ws.append(self.base_ws)
        for path, text in self.spec_files.items():
            await self.base_ws.write(path, text)
        self.round_base_files = self.base_files
        self.cur_ws = self.base_ws
        self.rt.frozen = set(self.frozen) | set(self.spec_files)
        self.rt.criteria_text = self.criteria_text()
        await self.hub.emit("plan", plan_event(self.plan))  # criteria may have been validated or downgraded
        self.pending_units = list(self.plan.units)
        self.first_round_ids = [u.id for u in self.plan.units]

    async def run_round(self) -> None:
        assert self.plan and self.rt
        self.round += 1
        units = self.pending_units
        await self.hub.emit("round", {"depth": self.round, "units": [u.id for u in units]})
        sched = Scheduler(self.rt)
        states = await sched.run(units, self.cur_ws, self.round_base_files, self.round, self.guidance)
        self.all_states.update(states)
        self.last_states = states

    async def integrate_and_verify(self) -> None:
        assert self.plan and self.rt
        states = self.last_states
        ig = await integrate(self.rt, self.cur_ws, self.round_base_files, states, self.round)
        self.last_integration = ig
        self.skipped_deletes += ig.skipped
        for uid in ig.merged_units:
            self.all_states[uid] = states[uid]
        self.changes.update(ig.changes)
        self.commits.extend(ig.commits)
        if self.cur_ws is not self.base_ws:
            with contextlib.suppress(Exception):
                await self.cur_ws.release()
        self.cur_ws = ig.ws
        self.owned_ws.append(ig.ws)
        self.round_base_files = overlay(self.round_base_files, ig.changes)
        await self.verify()

    async def verify(self) -> None:
        assert self.plan
        sem = asyncio.Semaphore(max(1, self.limits.max_workers))
        total_changes = {p: t for p, t in self.changes.items()}
        pol_ok, pol_detail = local_policy(total_changes, self.base_files, self.plan.task_type, self.isolation)
        sec_ok, sec_detail = local_secrets(total_changes)

        async def one(c: CriterionSpec) -> VerifyRow:
            async with sem:
                row = await self._verify_one(c)
            if c.kind == "policy" and not pol_ok:
                row.status, row.detail = "fail", f"policy violation: {pol_detail}"
            elif c.kind == "secrets" and not sec_ok:
                row.status, row.detail = "fail", f"secret-looking content: {sec_detail}"
            return row

        rows = await asyncio.gather(*(one(c) for c in self.plan.criteria))
        self.rows = list(rows)
        await self.flush_artifacts()
        counts = {"pass": 0, "fail": 0, "skip": 0, "advisory": 0}
        for r in self.rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        hard_pass = all(hard_ok(r) for r in self.rows if r.hard)
        await self.hub.emit("verify", {"round": self.round, "results": [r.event() for r in self.rows],
                                       "hard_pass": hard_pass, "summary": counts})

    async def _verify_one(self, c: CriterionSpec) -> VerifyRow:
        assert self.cur_ws is not None
        fork = await self.cur_ws.fork()
        spec = c
        if c.kind == "policy":  # builder B's policy verifier reads these params
            spec = c.model_copy(update={"params": {**c.params, "task_type": self.plan.task_type if self.plan else "",
                                                   "spec_files": sorted(self.spec_files)}})
        try:
            res = await self.deps.run_verifier(self.deps.criterion(spec), fork, self.baseline, self.store)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("verifier %s crashed: %s", c.kind, type(exc).__name__)
            return VerifyRow(c.id, c.kind, c.hard, "fail" if c.hard else "skip", None,
                             f"verifier error: {type(exc).__name__}: {str(exc)[:200]}")
        finally:
            with contextlib.suppress(BaseException):
                await asyncio.shield(fork.release())
        status = str(getattr(res, "status", "fail"))
        score = getattr(res, "score", None)
        detail = str(getattr(res, "detail", ""))
        arts = [str(getattr(a, "id", a)) for a in (getattr(res, "artifacts", None) or [])]
        if c.hard and status == "advisory":  # a promoted (strict) advisory criterion gates on its score
            threshold = float(c.params.get("threshold", 0.6))
            status = "pass" if score is not None and score >= threshold else "fail"
            detail = f"strict: score {score} vs threshold {threshold}. {detail}"
        elif not c.hard and status in ("pass", "fail"):
            note = f"downgraded ({c.downgraded})" if c.downgraded else "advisory"
            status, score = "advisory", (score if score is not None else (1.0 if status == "pass" else 0.0))
            detail = f"{note}: {detail}"
        elif not c.hard and status == "advisory":
            pass
        if status == "skip" and c.hard and detail.startswith("verifier error"):
            status = "fail"  # a crashed verifier is never mistaken for a pass
        if status not in ("pass", "fail", "skip", "advisory"):
            status = "fail" if c.hard else "skip"
        return VerifyRow(c.id, c.kind, c.hard, status, score, detail, arts)

    def hard_pass(self) -> bool:
        return bool(self.rows) and all(hard_ok(r) for r in self.rows if r.hard)

    def route_after_verify(self) -> str:
        if self.hard_pass() or self.round >= self.limits.max_rounds:
            return "finish"
        reason = self.budget.exhausted()
        if reason:
            self.stopped_reason = reason
            return "finish"
        return "critic"

    async def critic_step(self) -> None:
        assert self.plan and self.rt
        failing = [r for r in self.rows if r.hard and not hard_ok(r)]
        all_files = overlay(self.base_files, self.changes)
        lesson, units = await critique(self.rt, failing, all_files, sorted(self.changes), self.round, self.rt.frozen)
        await self.hub.emit("critic", {"node_id": self.round, "lesson": lesson, "model": getattr(self.llm_for("critic", "super"), "model", "")})
        self.pending_units = units
        self.guidance = {}

    # -- finish
    def final_files(self) -> dict[str, str]:
        out = {p: t for p, t in self.spec_files.items()}
        for p, t in self.changes.items():
            if t is not None:
                out[p] = t
        # only files that differ from the original
        return {p: t for p, t in out.items() if self.ctx.files.get(p) != t}

    async def finish(self) -> dict[str, Any]:
        ctx, plan = self.ctx, self.plan
        rows = self.rows
        final = self.final_files()
        needs_input, blocked = self.stop == "needs_input", self.stop == "blocked"
        landed = sum(1 for uid in self.first_round_ids if uid in self.all_states and self.all_states[uid].status == "merged")
        total = len(self.first_round_ids)
        if plan is None:
            outcome, reasons = ("needs_input" if needs_input else "failed"), ["no plan"]
            plan = Plan()
        else:
            failing_kinds = {r.kind for r in rows if r.hard and not hard_ok(r)}
            if not blocked and failing_kinds & set(PRECHECK_TYPES):
                blocked = True  # a policy/secrets violation is a block, not a plain failure
            outcome, reasons = compute_outcome(rows=rows, plan=plan, units_total=total, units_landed=landed,
                                               changed=bool(final), needs_input=needs_input, blocked=blocked)
        hard = [r for r in rows if r.hard]
        advisory = [{"id": r.criterion_id, "kind": r.kind, "score": r.score, "rationale": r.detail[:300]}
                    for r in rows if r.status == "advisory"]
        diff = make_diff({p: ctx.files.get(p) for p in final}, final, 20_000)
        by_kind = {r.kind: r for r in rows}
        pol, sec = by_kind.get("policy"), by_kind.get("security")
        best = {
            "id": 1, "depth": self.round, "idea": plan.summary, "code": "", "files": final, "diff": diff,
            "passed": sum(1 for r in hard if r.status == "pass"), "total": len(hard),
            "score": (sum(1 for r in hard if hard_ok(r)) / len(hard)) if hard else 0.0,
            "policy": {"ok": pol is None or hard_ok(pol), "reasons": [pol.detail[:200]] if pol and not hard_ok(pol) else []},
            "security": {"ok": sec is None or hard_ok(sec), "scanned": bool(sec and sec.status in ("pass", "fail")),
                         "reasons": []},
            "output": "\n".join(f"{r.status.upper():8} {r.criterion_id}: {r.detail[:160]}" for r in rows)[:1500],
            "outcome": outcome, "reasons": reasons, "deleted": sorted(p for p, t in self.changes.items() if t is None),
            "commits": [{"unit_id": c["unit_id"], "title": c["title"], "files": sorted(c["files"])} for c in self.commits],
        }
        guard_in = (ctx.guard_event or {}).get("verdict", "n/a")
        safety = {"guard": {"input": guard_in, "output": "n/a"},
                  "policy": {"candidates": total, "blocked": self.hub.denied, "reasons": [], "best_ok": best["policy"]["ok"]},
                  "security": {"scanner": "bandit", "scanned": best["security"]["scanned"], "blocked": 0 if best["security"]["ok"] else 1,
                               "best_ok": best["security"]["ok"]}}
        done = {
            "solved": outcome == "complete", "outcome": outcome, "task_type": plan.task_type, "best": best,
            "criteria": {"hard_pass": sum(1 for r in hard if hard_ok(r)), "hard_total": len(hard), "advisory": advisory},
            "usage": self.budget.usage(), "safety": safety, "engine": "swarm", "rounds": self.round,
            "candidates": len(self.all_states), "cancelled": sum(1 for s in self.all_states.values() if s.status == "cancelled"),
            "agents": {"spawned": self.hub.agents_spawned, "peak_parallel": self.budget.peak_parallel},
            "reasons": reasons,
        }
        if self.stopped_reason:
            done["stopped"] = "budget"
        ctx.result.update({
            "outcome": outcome, "task_type": plan.task_type, "plan": plan_event(plan) if self.plan else {},
            "criteria_rows": [r.event() for r in rows], "commits": self.commits, "spec_files": dict(self.spec_files),
            "final_files": final, "deleted": best["deleted"], "reasons": reasons, "agents": done["agents"],
            "criteria": done["criteria"], "plan_notes": list(plan.notes), "unit_summaries": {
                uid: (st.result.summary if st.result else "") for uid, st in self.all_states.items()},
            "advisory": advisory, "skipped_deletes": self.skipped_deletes,
        })
        ctx.result["best"] = best
        await self.hub.emit("done", done)
        return best

    async def teardown(self) -> None:
        for ws in [self.orig_ws, *self.owned_ws]:
            if ws is not None:
                with contextlib.suppress(BaseException):
                    await asyncio.shield(ws.release())


def _rs(config: RunnableConfig) -> RunState:
    return config["configurable"]["rs"]  # type: ignore[index]


async def n_prepare(state: GState, config: RunnableConfig) -> dict[str, Any]:
    rs = _rs(config)
    await rs.prepare()
    return {"route": "finish" if rs.stop else "spec"}


async def n_spec(state: GState, config: RunnableConfig) -> dict[str, Any]:
    await _rs(config).spec()
    return {}


async def n_round(state: GState, config: RunnableConfig) -> dict[str, Any]:
    await _rs(config).run_round()
    return {}


async def n_verify(state: GState, config: RunnableConfig) -> dict[str, Any]:
    rs = _rs(config)
    await rs.integrate_and_verify()
    return {"route": rs.route_after_verify()}


async def n_critic(state: GState, config: RunnableConfig) -> dict[str, Any]:
    await _rs(config).critic_step()
    return {}


async def n_finish(state: GState, config: RunnableConfig) -> dict[str, Any]:
    await _rs(config).finish()
    return {}


def _route(state: GState) -> str:
    return state.get("route", "finish")


def build_graph() -> Any:
    g = StateGraph(GState)
    for name, fn in (("prepare", n_prepare), ("spec", n_spec), ("round", n_round), ("verify", n_verify),
                     ("critic", n_critic), ("finish", n_finish)):
        g.add_node(name, fn)
    g.add_edge(START, "prepare")
    g.add_conditional_edges("prepare", _route, {"spec": "spec", "finish": "finish"})
    g.add_edge("spec", "round")
    g.add_edge("round", "verify")
    g.add_conditional_edges("verify", _route, {"critic": "critic", "finish": "finish"})
    g.add_edge("critic", "round")
    g.add_edge("finish", END)
    return g.compile()


_GRAPH: Any = None


def graph() -> Any:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


async def plan_only(ctx: SwarmCtx) -> Plan:
    """Plan without running anything (the repo flow uses it to choose between bugfix graph and swarm)."""
    limits = resolve_limits(ctx.settings, ctx.limits)
    budget = Budget(limits)
    llm_for = ctx.llm_factory
    repo_map = None
    if ctx.deps is not None:
        with contextlib.suppress(Exception):
            repo_map = await asyncio.to_thread(ctx.deps.build_repo_map, ctx.files)
    plan = await make_plan(ctx, llm_for("planner", "super"), budget, limits, repo_map)
    ctx.plan_usage = budget.usage()
    return plan


async def run_swarm(ctx: SwarmCtx) -> dict[str, Any]:
    """Run the swarm for one task. Emits the contract events through ctx.emit and returns `done.best`."""
    limits = resolve_limits(ctx.settings, ctx.limits)
    budget = Budget(limits)
    if ctx.plan_usage:
        budget.add_usage(ctx.plan_usage)
    hub = Hub(ctx.emit, Redactor(ctx.secrets))
    rs = RunState(ctx=ctx, hub=hub, budget=budget, limits=limits, llm_for=ctx.llm_factory, deps=ctx.deps)
    ctx.result["budget"] = budget
    ctx.result["hub"] = hub
    ticker = asyncio.create_task(budget_ticker(budget, hub.emit, ctx.budget_tick_s))
    config: RunnableConfig = {
        "configurable": {"rs": rs}, "recursion_limit": 30 + 8 * limits.max_rounds, "run_name": "patchloop-swarm",
        "tags": [f"run_id:{ctx.run_id}", "engine:swarm", f"mode:{ctx.mode}", *ctx.trace_tags],
        "metadata": {"run_id": ctx.run_id, "engine": "swarm", "mode": ctx.mode, "requested_type": ctx.task_type,
                     **ctx.trace_meta},
    }
    try:
        try:
            async with asyncio.timeout(limits.max_wall_s + 20):
                await graph().ainvoke({"route": ""}, config=config)
        except TimeoutError:
            await hub.emit("error", {"stage": "budget", "message": f"wall-time budget exhausted ({int(limits.max_wall_s)}s)"})
            rs.stopped_reason = "wall"
            await _ensure_done(rs)
        except asyncio.CancelledError:
            raise
        except SwarmDepsError as exc:
            await hub.emit("error", {"stage": "swarm", "message": str(exc)})
            await _ensure_done(rs)
        except Exception as exc:
            log.exception("swarm run %s failed", ctx.run_id)
            await hub.emit("error", {"stage": "swarm", "message": f"{type(exc).__name__}: {str(exc)[:200]}"})
            await _ensure_done(rs)
    finally:
        ticker.cancel()
        with contextlib.suppress(BaseException):
            await ticker
        await rs.teardown()
    return ctx.result.get("best", {})


async def _ensure_done(rs: RunState) -> None:
    """After an abnormal stop still emit exactly one `done` (outcome computed from whatever was verified)."""
    if "best" not in rs.ctx.result:
        with contextlib.suppress(Exception):
            await rs.finish()
