"""Deterministic verifiers (contract v3 section 6). Plain code decides; an LLM never grades a hard gate.

    results = [await run_verifier(c, ws, baseline, artifacts) for c in plan.criteria]

Kinds: build, tests, no_regression, policy, security, secrets, repro, acceptance_tests, characterization,
api_surface, lint_typecheck, complexity_metric, command, benchmark, ui_build_console, ui_overflow, ui_axe, ui_smoke,
advisory_vision, advisory_rubric. Every verifier returns pass / fail / skip (+ advisory for the advisory kinds) with
an explicit reason; `skip` never counts as a pass for a hard gate (the outcome logic decides what to do with it).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from app.swarm.artifacts import Artifact, ArtifactStore
from app.swarm.repo_map import RepoMap, build_repo_map
from app.swarm.verifiers import gates, ui  # noqa: F401  (registers the verifiers)
from app.swarm.verifiers.common import current_files, ensure_installed, run_tests, test_plan
from app.swarm.verifiers.registry import VERIFIERS, Ctx
from app.swarm.verifiers.types import Baseline, Criterion, VerifyResult

log = logging.getLogger(__name__)

__all__ = ["Criterion", "VerifyResult", "Baseline", "ArtifactStore", "Artifact", "run_verifier", "collect_baseline",
           "build_repo_map", "validate_on_original", "KINDS", "RepoMap"]

KINDS = tuple(sorted(VERIFIERS))
Judge = Callable[..., Awaitable[dict]]


async def run_verifier(c: Criterion, ws: Any, baseline: Baseline, artifacts: ArtifactStore, *,
                       judge: Judge | None = None) -> VerifyResult:
    """Run one criterion against the workspace's current state. Never raises; internal errors become `skip`."""
    fn = VERIFIERS.get(c.kind)
    if fn is None:
        return VerifyResult(c.id, c.kind, c.hard, "skip", None, f"unknown verifier kind {c.kind!r}")
    try:
        return await fn(c, Ctx(ws, baseline, artifacts, judge))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # a broken verifier must not be mistaken for a pass
        log.warning("verifier %s crashed: %s", c.kind, type(exc).__name__)
        return VerifyResult(c.id, c.kind, c.hard, "skip", None, f"verifier error: {type(exc).__name__}: {str(exc)[:200]}")


async def collect_baseline(ws: Any, repo_map: RepoMap | None = None, artifacts: ArtifactStore | None = None, *,
                           ui_checks: bool | None = None) -> Baseline:
    """Facts about the ORIGINAL repo: build status, passing test ids, lint counts, UI measurements + screenshots.

    Installs node dependencies in `ws` (so forks made afterwards inherit them). `ui_checks=None` auto-detects
    static web apps; False skips the browser step."""
    b = Baseline()
    b.files = await current_files(ws, b)
    rm = repo_map or build_repo_map(b.files)
    b.repo_map = rm
    status, detail, cmds = await gates.run_build(ws, rm)
    b.build = {"status": status, "detail": detail, "commands": cmds}
    fw, cmd = test_plan(rm)
    if not cmd:
        b.tests = {"status": "none", "command": "", "passing": set(), "failing": set(), "total": 0,
                   "detail": "no tests detected"}
    else:
        run = await run_tests(ws, b, b.files, rm=rm)
        assert run is not None
        b.tests = {"status": "pass" if run.code == 0 else "fail", "command": cmd, "framework": fw,
                   "passing": run.passing, "failing": run.failing, "total": len(run.results), "code": run.code,
                   "detail": run.output[-300:] if run.code else f"{len(run.passing)} passing"}
        if run.code != 0 and not run.results:
            b.notes.append(f"original test run failed to produce per-test results (exit {run.code})")
    b.lint = await gates.run_lint(ws, rm)
    if ui_checks is not False:
        b.ui = await ui.collect_ui_baseline(ws, rm, b.files)
        if artifacts is not None and b.ui.get("shots"):
            ui.add_shots(artifacts, "before", b.ui["shots"])
    else:
        b.ui = {"status": "skip", "reason": "ui checks disabled"}
    return b


async def validate_on_original(c: Criterion, ws: Any, baseline: Baseline, artifacts: ArtifactStore) -> tuple[bool, str]:
    """Spec-phase check (run on an ORIGINAL fork): acceptance/repro tests must FAIL there, characterization tests and
    smoke scripts must PASS there. Returns (valid, reason)."""
    res = await run_verifier(c, ws, baseline, artifacts)
    if res.status == "skip":
        return False, f"cannot validate: {res.detail}"
    if c.kind in ("acceptance_tests", "repro"):
        if res.status == "fail":
            return True, "fails on the original as required"
        return False, "passes on the original, so it does not test the requested change"
    if c.kind in ("characterization", "ui_smoke", "command"):
        if res.status == "pass":
            return True, "passes on the original as required"
        return False, f"does not pass on the original: {res.detail}"
    return True, res.detail
