"""Planner and spec agents. The LLM proposes a plan and verification assets; this module SANITISES them in code:
env caps clamp the swarm, paths are policy-checked, mandatory hard gates are added per task type, and every synthesized
verifier is run against the ORIGINAL code and rejected (retry, then downgrade to advisory with a stated reason) unless it
behaves as the task type requires. Nothing is silently dropped."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from app.policy import MAX_REPO_FILE_BYTES, path_violation
from app.repo_detect import is_test_path
from app.swarm.budget import Budget, Limits
from app.swarm.events import Hub, looks_secret
from app.swarm.prompts import PLANNER_SYSTEM, SPEC_SYSTEM, planner_user, spec_user
from app.swarm.tools import check_command, list_symbols, scopes_overlap
from app.swarm.types import (ADVISORY_KINDS, SYNTHESIZED_KINDS, CriterionSpec, Plan, Question, SwarmCtx, SwarmSizing,
                             Unit, cycle)
from app.swarm.workers import ChatLLM, parse_json_any, syntax_problem

log = logging.getLogger(__name__)

MANDATORY_HARD = ("build", "no_regression", "policy", "security", "secrets")
TYPE_REQUIRED: dict[str, tuple[str, ...]] = {
    "bugfix": ("repro",),
    "feature": ("acceptance_tests",),
    "refactor": ("characterization", "api_surface", "lint_typecheck"),
    "ui": ("ui_build_console", "ui_overflow", "ui_axe", "ui_smoke"),
}
TYPE_ADVISORY: dict[str, tuple[str, ...]] = {"ui": ("advisory_vision", "advisory_rubric")}
TASK_VERIFIER_KINDS = {"acceptance_tests", "characterization", "repro", "command", "benchmark", "tests", "ui_smoke"}
DESCRIPTIONS = {
    "build": "install + build/compile/typecheck succeed", "no_regression": "every test that passed before still passes",
    "policy": "path policy: no .github, no edits to existing tests, no path escape, bounded file count",
    "security": "no new high-severity findings", "secrets": "no secret-looking strings added",
    "repro": "reproducer fails on the original and passes now", "acceptance_tests": "acceptance tests written first pass now",
    "characterization": "behaviour pinned on the original is unchanged", "api_surface": "public exports/signatures unchanged",
    "lint_typecheck": "lint/typecheck no worse", "ui_build_console": "UI builds and loads with no console errors",
    "ui_overflow": "no horizontal overflow at 375/768/1280 px", "ui_axe": "accessibility violations not increased",
    "ui_smoke": "key-flow smoke script passes before and after",
    "advisory_vision": "vision review of before/after screenshots", "advisory_rubric": "readability / plan-adherence review",
    "tests": "the test suite passes", "command": "command exits 0", "benchmark": "benchmark meets its threshold",
    "complexity_metric": "the stated complexity metric improved",
}


class LLMJsonError(RuntimeError):
    pass


async def json_call(llm: ChatLLM, system: str, user: str, model_cls: type[BaseModel], *, key: str, budget: Budget,
                    tries: int = 3) -> BaseModel:
    """Structured JSON from a chat model: parse, validate with pydantic, and on failure show the error back to the
    model (repair-on-invalid). Raises LLMJsonError after `tries`."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last = ""
    for _ in range(tries):
        reply = await llm.respond(messages, None, key=key)
        budget.add_usage(reply.usage)
        data = parse_json_any(reply.content)
        try:
            if data is None:
                raise ValueError("no JSON object found in the reply")
            return model_cls.model_validate(data)
        except (ValueError, ValidationError) as exc:
            last = str(exc)[:400]
            messages += [{"role": "assistant", "content": (reply.content or "")[:3000]},
                         {"role": "user", "content": f"That was not valid: {last}\nReply ONLY with the corrected ```json object."}]
    raise LLMJsonError(f"{key}: invalid JSON after {tries} tries: {last}")


# ---- repository digest ------------------------------------------------------------------------

def digest(files: dict[str, str], repo_map: Any = None, cap: int = 14_000) -> str:
    """Compact map for prompts: never the file contents of a large repo, just tree + symbols + entry points."""
    fn = getattr(repo_map, "digest", None) or getattr(repo_map, "render", None)
    if callable(fn):
        try:
            text = str(fn())
            if text:
                return text[:cap]
        except Exception:
            pass
    paths = sorted(files)
    lines = [f"{len(paths)} files"]
    tests = [p for p in paths if is_test_path(p)]
    if tests:
        lines.append("tests: " + ", ".join(tests[:20]) + (f" (+{len(tests) - 20})" if len(tests) > 20 else ""))
    for manifest in ("package.json", "pyproject.toml", "setup.py", "requirements.txt", "go.mod", "Cargo.toml"):
        if manifest in files:
            lines.append(f"manifest {manifest}: " + files[manifest][:500].replace("\n", " "))
    lines.append("files (path: symbols):")
    for p in paths:
        if is_test_path(p):
            continue
        syms = ", ".join(n for _, n in list_symbols(files[p], 6)) if p.endswith(
            (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java")) else ""
        lines.append(f"- {p} ({len(files[p])}b){': ' + syms if syms else ''}")
        if sum(len(x) for x in lines) > cap:
            lines.append("... (map truncated; use list_dir/search tools)")
            break
    return "\n".join(lines)[:cap]


# ---- sanitising the plan -----------------------------------------------------------------------

def _clean_scope(entry: str, task_type: str, notes: list[str], unit_id: str) -> str | None:
    e = (entry or "").strip().replace("\\", "/")
    while e.startswith("./"):
        e = e[2:]
    if not e or len(e) > 200:
        return None
    probe = e.rstrip("/").replace("*", "x").replace("?", "x").replace("[", "x").replace("]", "x")
    bad = path_violation(probe) if probe else "empty"
    if bad:
        notes.append(f"unit {unit_id}: dropped scope entry {entry!r} ({bad})")
        return None
    if is_test_path(probe) and task_type != "tests":
        notes.append(f"unit {unit_id}: dropped test path {entry!r} (tests are immutable for this task type)")
        return None
    return e


def finalize_plan(plan: Plan, *, requested_type: str, strict: list[str], limits: Limits, files: dict[str, str],
                  answers: dict[str, str]) -> Plan:
    """Make an LLM plan safe and complete. Never trusts model-requested sizes."""
    notes = list(plan.notes)
    if requested_type != "auto":
        plan.task_type, plan.task_type_source = requested_type, "user"
    else:
        plan.task_type_source = "auto"
    if answers:
        plan.clarify = []
    plan.clarify = plan.clarify[:3]
    units: list[Unit] = []
    for u in plan.units[: limits.max_units]:
        scope = [s for s in (_clean_scope(x, plan.task_type, notes, u.id) for x in u.scope_files) if s]
        u.scope_files = list(dict.fromkeys(scope))[:40]
        u.variants = max(1, min(u.variants, 3, limits.max_workers))
        u.depends_on = [d for d in u.depends_on if d != u.id]
        u.checks = [c for c in u.checks if check_command(c) is None][:4]
        units.append(u)
    if len(plan.units) > limits.max_units:
        notes.append(f"plan had {len(plan.units)} units; kept the first {limits.max_units} (SWARM_MAX_UNITS)")
    ids = {u.id for u in units}
    for u in units:
        u.depends_on = [d for d in u.depends_on if d in ids]
    if cycle(units):
        for u in units:
            u.depends_on = []
        notes.append("unit dependency cycle removed (units run independently)")
    plan.units = units
    plan.criteria = normalize_criteria(plan.criteria, plan.task_type, strict, notes)
    planned = sum(u.variants for u in units) or 1
    widest = max(1, planned)
    asked = plan.swarm.max_parallel if plan.swarm.max_parallel > 0 else widest
    plan.swarm = SwarmSizing(max_parallel=max(1, min(asked, limits.max_workers, widest)),
                             workers_planned=planned, limits=limits.public())
    if not plan.summary:
        plan.summary = f"{plan.task_type} task in {len(units)} unit(s)"
    plan.notes = notes
    return plan


def normalize_criteria(given: list[CriterionSpec], task_type: str, strict: list[str], notes: list[str]) -> list[CriterionSpec]:
    out: list[CriterionSpec] = []
    seen: set[str] = set()
    for c in given:
        if c.id in seen:
            continue
        seen.add(c.id)
        if c.kind in MANDATORY_HARD:
            c.hard = True  # the model cannot soften the baseline gates
        if c.kind in ("command", "benchmark"):
            cmd = str(c.params.get("command", ""))
            bad = check_command(cmd) if cmd else "no params.command given"
            if bad:
                c.hard, c.downgraded = False, f"verifier command not runnable ({bad})"
                notes.append(f"criterion {c.id}: downgraded to advisory: {c.downgraded}")
        out.append(c)
    have = {c.kind for c in out}

    def add(kind: str, hard: bool = True) -> None:
        cid = kind
        while cid in seen:
            cid += "_"
        seen.add(cid)
        out.append(CriterionSpec(id=cid, kind=kind, hard=hard, description=DESCRIPTIONS.get(kind, kind)))
        have.add(kind)

    for kind in MANDATORY_HARD:
        if kind not in have:
            add(kind)
    for kind in TYPE_REQUIRED.get(task_type, ()):
        if kind not in have:
            add(kind)
    for kind in TYPE_ADVISORY.get(task_type, ()):
        if kind not in have:
            add(kind, hard=False)
    for c in out:
        if c.kind in TYPE_REQUIRED.get(task_type, ()) and not c.hard and not c.downgraded:
            c.hard = True  # type-specific gates are not optional
    if task_type not in TYPE_REQUIRED and not any(c.hard and c.kind in TASK_VERIFIER_KINDS for c in out):
        notes.append("NO_EXECUTABLE_TASK_VERIFIER: only build/no_regression/policy/security/secrets gate this task, "
                     "so the best possible outcome is partial")
    by_key = {c.id: c for c in out}
    by_kind = {c.kind: c for c in out}
    for name in strict:
        c = by_key.get(name) or by_kind.get(name)
        if c is None:
            notes.append(f"strict criterion {name!r} not in the plan: ignored")
        elif not c.hard:
            c.hard = True
            c.params.setdefault("threshold", 0.6)
            c.params["promoted"] = True
            c.downgraded = ""
    return out


def has_task_verifier(plan: Plan) -> bool:
    if plan.task_type in TYPE_REQUIRED:
        return all(any(c.kind == k and c.hard for c in plan.criteria) for k in TYPE_REQUIRED[plan.task_type])
    return any(c.hard and c.kind in TASK_VERIFIER_KINDS for c in plan.criteria)


def fallback_plan(ctx: SwarmCtx, limits: Limits, requested_type: str, why: str) -> Plan:
    """Deterministic plan used when the planner model returns nothing usable. The task is never declined."""
    from app.repo_agents import heuristic_locate

    ttype = requested_type if requested_type != "auto" else "other"
    scope = [h["path"] for h in heuristic_locate(ctx.task, ctx.files, 6)]
    if not scope:
        scope = [p for p in sorted(ctx.files, key=lambda x: -len(ctx.files[x])) if not is_test_path(p)][:5]
    plan = Plan(task_type=ttype, summary="Single-unit fallback plan: " + ctx.task.strip().splitlines()[0][:200],
                units=[Unit(id="u1", title="Do the task", scope_files=scope, instructions=ctx.task[:1500])],
                notes=[f"fallback plan: {why}"])
    return finalize_plan(plan, requested_type=requested_type, strict=ctx.strict, limits=limits, files=ctx.files,
                         answers=ctx.answers)


async def make_plan(ctx: SwarmCtx, llm: ChatLLM, budget: Budget, limits: Limits, repo_map: Any) -> Plan:
    user = planner_user(ctx.task, ctx.task_type, digest(ctx.files, repo_map), ctx.answers, limits.public())
    try:
        out = await json_call(llm, PLANNER_SYSTEM, user, Plan, key="planner", budget=budget)
    except LLMJsonError as exc:
        log.warning("planner failed: %s", str(exc)[:200])
        return fallback_plan(ctx, limits, ctx.task_type, "the planner returned invalid JSON three times")
    assert isinstance(out, Plan)
    plan = finalize_plan(out, requested_type=ctx.task_type, strict=ctx.strict, limits=limits, files=ctx.files,
                         answers=ctx.answers)
    if not plan.clarify and not plan.units and not plan.cheap_path:
        return fallback_plan(ctx, limits, ctx.task_type, "the plan contained no units")
    return plan


# ---- spec agents ---------------------------------------------------------------------------------

class SpecOut(BaseModel):
    files: dict[str, str] = {}
    command: str = ""
    steps: list[dict[str, Any]] = []
    note: str = ""


def _spec_problem(kind: str, out: SpecOut, files: dict[str, str]) -> str:
    if kind == "ui_smoke":
        if not out.steps and not out.files:
            return "ui_smoke needs `steps` (or a script file)"
    elif not out.files:
        return "no test files were returned"
    for path, text in out.files.items():
        bad = path_violation(path)
        if bad:
            return bad
        if path in files:
            return f"{path} already exists: new files only, never overwrite"
        if len(text.encode()) > MAX_REPO_FILE_BYTES:
            return f"{path} is too large"
        prob = syntax_problem(path, text)
        if prob:
            return f"syntax error: {prob}"
        if looks_secret(text):
            return f"{path} contains a secret-looking string"
    if kind != "ui_smoke" and not any(is_test_path(p) for p in out.files):
        return "the files must be test files (under a tests/ directory or named test_*.py / *.test.js)"
    if out.command and check_command(out.command):
        return f"command not allow-listed: {check_command(out.command)}"
    return ""


EXPECT_ON_ORIGINAL = {"acceptance_tests": "fail", "repro": "fail", "characterization": "pass", "ui_smoke": "pass"}


async def synthesize_verifiers(ctx: SwarmCtx, plan: Plan, orig_ws: Any, baseline: Any, store: Any, hub: Hub,
                               budget: Budget, llm_for: Callable[[str, str], ChatLLM], context: str, isolation: str,
                               on_artifacts: Callable[[], Any] | None = None) -> set[str]:
    """Write + validate acceptance / characterization / smoke assets. Returns the protected (frozen) file paths."""
    frozen: set[str] = set()
    targets = [c for c in plan.criteria if c.kind in SYNTHESIZED_KINDS and c.hard and not c.params.get("files")
               and not c.params.get("steps")]

    async def one(c: CriterionSpec) -> None:
        llm = llm_for("spec", "super")
        agent_id = f"spec.{c.id}"
        model = getattr(llm, "model", "")
        await hub.agent(agent_id, "spec", "spawned", model=model, isolation=isolation)
        await hub.agent(agent_id, "spec", "running", model=model, isolation=isolation)
        feedback, verdict = "", ""
        expect = EXPECT_ON_ORIGINAL[c.kind]
        for attempt in range(3):
            if budget.exhausted():
                feedback = budget.exhausted()
                break
            try:
                out = await json_call(llm, SPEC_SYSTEM, spec_user(c.kind, ctx.task, c.description, context, feedback),
                                      SpecOut, key=f"spec:{c.id}:{attempt}", budget=budget, tries=2)
            except LLMJsonError as exc:
                feedback = str(exc)[:300]
                continue
            assert isinstance(out, SpecOut)
            problem = _spec_problem(c.kind, out, ctx.files)
            if problem:
                feedback = problem
                continue
            probe = CriterionSpec(id=c.id, kind=c.kind, hard=True, description=c.description,
                                  params={**c.params, "files": out.files, "command": out.command, "steps": out.steps})
            fork = await orig_ws.fork()
            try:
                res = await ctx.deps.run_verifier(ctx.deps.criterion(probe), fork, baseline, store)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                feedback = f"the verifier crashed on your assets: {type(exc).__name__}"
                continue
            finally:
                await fork.release()
            status = str(getattr(res, "status", "fail"))
            detail = str(getattr(res, "detail", ""))
            if status == "skip":
                c.params.update(probe.params)  # cannot be validated here (e.g. no browser): keep, say so
                c.params["validation"] = f"unvalidated: verifier skipped ({detail[:120]})"
                verdict = "unvalidated"
                break
            if status == expect:
                c.params.update(probe.params)
                c.params["validation"] = f"validated: {expect}s on the original code"
                frozen.update(out.files)
                verdict = "ok"
                break
            feedback = (f"On the ORIGINAL code your {c.kind} {'passed' if status == 'pass' else 'failed'} but it must "
                        f"{expect}.\n{detail[:600]}")
        if verdict:
            await hub.agent(agent_id, "spec", "done", model=model, isolation=isolation,
                            summary=f"{c.kind} {c.params.get('validation', '')}"[:200])
            return
        c.hard = False
        c.downgraded = f"could not synthesize a validated {c.kind}: {feedback[:200]}"
        plan.notes.append(f"criterion {c.id}: downgraded to advisory: {c.downgraded}")
        await hub.agent(agent_id, "spec", "failed", model=model, isolation=isolation, summary=c.downgraded)

    await asyncio.gather(*(one(c) for c in targets))
    for c in plan.criteria:  # assets already present in the plan (e.g. scripted) are protected too
        frozen.update((c.params.get("files") or {}).keys())
    return frozen


def plan_event(plan: Plan) -> dict[str, Any]:
    """The `plan` event payload exactly per contract section 4."""
    return {
        "task_type": plan.task_type, "task_type_source": plan.task_type_source, "summary": plan.summary,
        "criteria": [{"id": c.id, "kind": c.kind, "hard": c.hard, "description": c.description,
                      "verifier": c.verifier or c.kind,
                      **({"downgraded": c.downgraded} if c.downgraded else {}),
                      **({"validation": c.params["validation"]} if c.params.get("validation") else {})}
                     for c in plan.criteria],
        "units": [{"id": u.id, "title": u.title, "scope_files": u.scope_files, "depends_on": u.depends_on,
                   "variants": u.variants, "role": u.role} for u in plan.units],
        "swarm": {"max_parallel": plan.swarm.max_parallel, "workers_planned": plan.swarm.workers_planned,
                  "limits": plan.swarm.limits},
        "notes": plan.notes[:12],
    }
