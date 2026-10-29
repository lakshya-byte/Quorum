"""The repo task pipeline (POST /repo-runs):

  repo -> guard -> locate -> repro -> [engine: triage, round, node..., critic, done] -> pr

Everything before the engine streams within milliseconds so the UI shows progress at once. The engine is the
existing LangGraph team; this module only adapts a repo task to its bug-like shape (see app/repo_eval.py).
The per-run GitHub token is used for the tarball download and the PR, never logged, stored or emitted.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import LOCAL_TEST_TIMEOUT, SANDBOX_TEST_TIMEOUT
from app.graph_engine import BudgetExceeded, GraphCtx, run_graph
from app.policy import ast_violations, path_violation
from app.repo_agents import first_test_name, heuristic_locate, repro_path_for
from app.repo_detect import is_test_path
from app.repo_eval import build_repo_bug, run_tests
from app.repo_loader import RepoError, RepoSnapshot, demo_names, fetch_github, load_demo
from app.repo_pr import PRError, fake_pr, open_repo_pr, push_followup, redact, repo_pr_body
from app.scoring import parse_results
from app.telemetry import background_run, run_id_var, trace_id_var

log = logging.getLogger(__name__)

REPO_TEST_TIMEOUT = 60
REJECT_MARKERS = ("ModuleNotFoundError", "ImportError", "SyntaxError", "IndentationError")


@dataclass
class RepoSpec:
    task: str
    full_name: str
    branch: str = "main"
    token: str = field(default="", repr=False)
    auto_pr: bool = True
    user_id: str | None = None
    engine: str | None = None
    run_url: str = ""
    followup: dict[str, Any] | None = None
    source: str = "api"
    issue_ref: int | None = None


def resolve_demo(full_name: str, fake_mode: bool) -> str | None:
    """Bundled demo repo for this request: `demo/<name>`, or (fake mode only) the closest bundled repo."""
    names = demo_names()
    short = full_name.split("/", 1)[-1].lower()
    if full_name.startswith("demo/"):
        return short if short in names else None
    if fake_mode:
        return short if short in names else (names[0] if names else None)
    return None


def task_text(spec: RepoSpec) -> str:
    if not spec.followup:
        return spec.task
    prev = ", ".join(sorted((spec.followup.get("previous_files") or {}))) or "(none)"
    return (f"{spec.task}\n\nA fix is already applied on the pull request branch (files: {prev}).\n"
            f"The reviewer asks for this change:\n{spec.followup.get('message', '')}")


def safe_previous(files: dict[str, Any] | None) -> dict[str, str]:
    return {p: c for p, c in (files or {}).items() if isinstance(c, str) and path_violation(p) is None
            and not is_test_path(p)}


async def load_snapshot(reg: Any, run: Any, spec: RepoSpec, demo_name: str | None) -> RepoSnapshot:
    if demo_name:
        snap = load_demo(demo_name, spec.branch)
    else:
        branch = (spec.followup or {}).get("pr_branch") or spec.branch
        snap = await reg.repo_fetcher(spec.full_name, branch, spec.token)
    if spec.followup:  # start from the PR branch contents (idempotent when the branch already has them)
        snap.files.update(safe_previous(spec.followup.get("previous_files")))
    return snap


def repro_command(snap: RepoSnapshot, path: str) -> str:
    if snap.framework == "unittest":
        return f"python -m unittest {path[:-3].replace('/', '.')}"
    return f"python -m pytest -q -x --no-header -p no:cacheprovider {path}"


async def validate_reproducer(bug: dict[str, Any], sandbox: Any, snap: RepoSnapshot, path: str, text: str,
                              timeout: int) -> tuple[bool, str]:
    """Accepted ONLY if it runs and FAILS on the original code (not because of a broken test file)."""
    bad = path_violation(path) or (ast_violations(text)[:1] or [None])[0]
    if bad:
        return False, f"rejected: {bad}"
    files = {path: text}
    if bug.get("checkpoint") is not None:
        code, out = await sandbox.run_repo(files, repro_command(snap, path), timeout, base=bug["checkpoint"])
    else:
        code, out = await sandbox.run_repo({**snap.files, **files}, repro_command(snap, path), timeout)
    passed, total = parse_results(out, code, snap.language)
    if any(m in out for m in REJECT_MARKERS):
        return False, "the reproducer could not run (import or syntax error):\n" + out[-600:]
    if total == 0:
        return False, "the reproducer ran no tests:\n" + out[-400:]
    if passed == total:
        return False, "the reproducer PASSES on the original code, so it does not show the bug:\n" + out[-400:]
    return True, out[-1200:]


async def run_repo_task(reg: Any, run: Any, spec: RepoSpec, demo_name: str | None) -> None:
    run_id_var.set(run.run_id)
    trace_id_var.set(run.trace_id)
    status, ctx, sandbox, handle = "done", None, None, None

    async def emit(kind: str, data: dict[str, Any]) -> None:
        run.emit(kind, data)

    with background_run("run/repo", run.trace_headers):
        try:
            sandbox = reg._sandbox(run.mode)
            status, ctx, handle = await _pipeline(reg, run, spec, demo_name, sandbox, emit)
        except BudgetExceeded:
            status = "budget"
        except RepoError as exc:
            run.emit("error", {"stage": "repo", "message": redact(str(exc), spec.token)})
            status = "error"
        except Exception as exc:
            log.exception("repo run %s failed", run.run_id)
            run.emit("error", {"stage": "engine", "message": redact(f"{type(exc).__name__}: {exc}", spec.token)})
            status = "error"
        finally:
            handle = handle or getattr(run, "_handle", None)
            if sandbox is not None and handle is not None:
                try:
                    await sandbox.release(handle)
                except Exception:
                    log.warning("could not release the sandbox checkpoint")
        run._token = ""  # the credential is not needed after the PR attempt
        run.finish(status)
        reg._record_metrics(run, ctx)
    reg.save(run)
    await reg._report(run)


async def _pipeline(reg: Any, run: Any, spec: RepoSpec, demo_name: str | None, sandbox: Any, emit: Any):
    s = reg.settings
    snap = await load_snapshot(reg, run, spec, demo_name)
    run.repo, run.branch = snap.full_name, snap.branch
    run.emit("repo", {"full_name": snap.full_name, "branch": snap.branch, "files": len(snap.files),
                      "language": snap.language, "test_command": snap.test_command, "truncated": snap.truncated,
                      "support": snap.support, "demo": snap.demo})
    if not snap.demo and run.mode != "live" and not s.allow_local_repo_exec:
        # a real repository's tests are arbitrary code: never run them on the agent host
        run.emit("error", {"stage": "sandbox", "message": "real repositories run only in an isolated Nebius Sandbox "
                                                          "(PATCHLOOP_MODE=live with Nebius credentials)"})
        run.emit("done", {"solved": False, "best": None, "usage": zero(), "engine": "graph", "rounds": 0,
                          "candidates": 0, "cancelled": 0, "stopped": "no_sandbox"})
        return "error", None, None
    text = task_text(spec)
    team =reg.team(run.mode, run.model_override if hasattr(run, "model_override") else None)
    config = {"run_name": "patchloop-repo", "tags": [f"run_id:{run.run_id}", "kind:repo", f"source:{run.source}"],
              "metadata": {"run_id": run.run_id, "repo": snap.full_name, "source": run.source or "api",
                           "kind": "repo", "mode": run.mode}}
    usage_parts: list[dict[str, int]] = []

    # 1. untrusted text is guarded BEFORE any agent reads it
    guard_event = await reg.guard.check("input", text, run.mode, run.run_id)
    run.emit("guard", guard_event)
    if guard_event["verdict"] != "pass":
        run.emit("error", {"stage": "input_guard",
                           "message": "input blocked by guardrails: " + "; ".join(guard_event["reasons"])})
        run.emit("done", {"solved": False, "best": None, "usage": zero(), "engine": "graph", "rounds": 0,
                          "candidates": 0, "cancelled": 0, "stopped": "guard"})
        return "blocked", None, None

    if not snap.test_command:
        run.emit("error", {"stage": "tests", "message": "no test command could be detected for this repository "
                                                         "(supported: Python unittest/pytest; Node and Go best-effort)"})
        run.emit("done", {"solved": False, "best": None, "usage": zero(), "engine": "graph", "rounds": 0,
                          "candidates": 0, "cancelled": 0, "stopped": "no_tests"})
        return "done", None, None

    # 2. locator
    hint = snap.meta.get("locate") if snap.demo else None
    located, used = await team.locate(text, snap.files, config, run.run_id, hint=hint)
    usage_parts.append(used)
    located = [x for x in located if x["path"] in snap.files and not is_test_path(x["path"])] \
        or heuristic_locate(text, snap.files)
    run.emit("locate", {"files": located})
    if not located:
        run.emit("error", {"stage": "locate", "message": "could not find source files related to the task"})
        run.emit("done", {"solved": False, "best": None, "usage": merge_usage(usage_parts), "engine": "graph",
                          "rounds": 0, "candidates": 0, "cancelled": 0, "stopped": "locate"})
        return "done", None, None

    bug = build_repo_bug(snap, text, [x["path"] for x in located], run.run_id)
    bug["issue"] = text
    bug["title"] = spec.task.strip().splitlines()[0][:100] if spec.task.strip() else bug["title"]
    if spec.followup:
        bug["followup_note"] = " ".join(str(spec.followup.get("message", "")).split())[:80] or "requested change"
    timeout = SANDBOX_TEST_TIMEOUT if run.mode == "live" else max(LOCAL_TEST_TIMEOUT, REPO_TEST_TIMEOUT)
    handle = await sandbox.checkpoint(snap.files)
    run._handle = handle  # released by run_repo_task even if a later stage raises
    bug["checkpoint"] = handle

    # 3. test-writer: the reproducer is accepted only if it FAILS on the original code
    if snap.language == "python":
        path = repro_path_for(snap.files)
        bug["fake_repro"] = next(iter((snap.meta.get("repro_text") or {}).values()), "") if snap.demo else ""
        feedback, accepted, tail, last_text = "", False, "", ""
        for _attempt in range(2):
            text_r, used = await team.write_repro(bug, path, feedback, config, run.run_id)
            usage_parts.append(used)
            last_text = text_r or last_text
            if not text_r:
                feedback, tail = "no test code was returned", "no reproducer returned"
                continue
            accepted, tail = await validate_reproducer(bug, sandbox, snap, path, text_r, timeout)
            if accepted:
                bug["tests"], bug["reproducer_path"] = text_r, path
                run.repro_path = path
                break
            feedback = tail
        run.emit("repro", {"path": path, "test_name": first_test_name(bug["tests"] or last_text),
                           "failed_on_original": accepted, "output_tail": tail[-800:]})
    else:
        run.emit("repro", {"path": "", "test_name": "", "failed_on_original": False,
                           "output_tail": f"reproducer generation supports Python only (language: {snap.language})"})

    # 4. without a failing signal there is nothing to fix against (except an explicit reviewer follow-up)
    if not bug["tests"] and not spec.followup:
        code, out = await run_tests(bug, sandbox, {}, timeout)
        passed, total = parse_results(out, code, snap.language)
        if total == 0 or passed == total:
            msg = ("no tests were discovered" if total == 0 else
                   "all existing tests already pass and no failing reproducer could be written, so a fix cannot be verified")
            run.emit("error", {"stage": "repro", "message": msg})
            run.emit("done", {"solved": False, "best": None, "usage": merge_usage(usage_parts), "engine": "graph",
                              "rounds": 0, "candidates": 0, "cancelled": 0, "stopped": "no_signal"})
            return "done", None, handle

    # 5. the existing team engine
    async def emit(kind: str, data: dict[str, Any]) -> None:
        run.emit(kind, data)

    ctx = GraphCtx(
        run_id=run.run_id, bug=bug, mode=run.mode, settings=s, sandbox=sandbox, team=team, guard=reg.guard,
        emit=emit, test_timeout=timeout, pre_guard=guard_event,
        trace_tags=[f"repo:{snap.full_name}", f"source:{run.source or 'api'}", "kind:repo"],
        trace_meta={"repo": snap.full_name, "source": run.source or "api", "kind": "repo"},
    )
    for used in usage_parts:
        ctx.add_usage(used)
    await run_graph(ctx)
    run.pr_draft = ctx.pr_draft
    run.cause = next((e["data"].get("cause", "") for e in run.events if e["type"] == "triage"), "")
    best = run.done_event().get("best") or {}
    run.files_changed = len(best.get("files") or {}) if run.done_event().get("solved") else 0

    # 6. pull request (after done; the callback is sent after this so it carries pr_url)
    if run.done_event().get("solved") and spec.auto_pr:
        try:
            await open_run_pr(reg, run, spec.token)
        except PRError as exc:
            run.emit("error", {"stage": "pr", "message": redact(str(exc), spec.token)})
        except Exception as exc:
            log.warning("opening the PR failed: %s", type(exc).__name__)
            run.emit("error", {"stage": "pr", "message": f"could not open the pull request: {type(exc).__name__}"})
    status = "blocked" if any(e["type"] == "error" and e["data"].get("stage") == "input_guard"
                              for e in run.events) else "done"
    return status, ctx, handle


def zero() -> dict[str, int]:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def merge_usage(parts: list[dict[str, int]]) -> dict[str, int]:
    out = zero()
    for p in parts:
        out["calls"] += 1
        out["prompt_tokens"] += p.get("prompt_tokens", 0)
        out["completion_tokens"] += p.get("completion_tokens", 0)
    return out


async def open_run_pr(reg: Any, run: Any, token: str) -> dict[str, Any]:
    """Open (or update, for follow-ups) the PR of a solved repo run. Idempotent. Used by the flow and by
    POST /runs/{id}/pr. Fake for demo repos; real PRs need `token`."""
    async with run._pr_lock:
        if run.pr_url:
            return pr_info(run)
        done = run.done_event()
        best = done.get("best") or {}
        files = best.get("files") or {}
        if not done.get("solved") or not files:
            raise PRError("run is not solved")
        followup = run.followup or None
        draft = run.pr_draft if run.pr_draft and run.pr_draft.get("guard") == "pass" else None
        label = "an isolated Nebius Sandbox" if run.mode in ("live", "replay") else "an isolated local sandbox"
        shim = {"issue": run.task, "reproducer_path": run.repro_path}
        safety = done.get("safety")
        title = ((draft or {}).get("title") or f"fix: {run.task.strip().splitlines()[0][:100]}")[:200]

        async def body(include_untrusted: bool) -> str:
            return repo_pr_body(shim, best, cause=run.cause, draft=draft, label=label, run_url=run.run_url,
                                issue_ref=run.issue_ref, safety=safety, include_untrusted=include_untrusted)

        text = await body(True)
        verdict = await reg.guard.check("output", f"{title}\n\n{text}", run.mode, run.run_id)
        if verdict["verdict"] != "pass":  # fall back to the deterministic template without task/model text
            title, text = "fix: automated change", await body(False)
        if run.demo:
            info = fake_pr(run.repo, run.task, run.run_id, followup)
        else:
            if not token:
                raise PRError("a GitHub token is required to open the pull request")
            api = reg.github_factory(token)
            try:
                if followup and followup.get("pr_branch"):
                    info = await push_followup(api, run.repo, followup["pr_branch"], int(followup.get("pr_number") or 0),
                                               files, f"PatchLoop follow-up: {(followup.get('message') or '')[:100]}",
                                               pr_url=followup.get("pr_url", ""))
                    if not info["url"]:
                        info["url"] = f"https://github.com/{run.repo}/pull/{info['number']}"
                else:
                    info = await open_repo_pr(api, run.repo, run.branch, files, title, text, run.task)
            except PRError:
                raise
            except Exception as exc:
                raise PRError(redact(f"GitHub error: {type(exc).__name__}", token)) from None
            finally:
                close = getattr(api, "aclose", None)
                if close:
                    await close()
        run.pr_url, run.pr_number, run.pr_branch = info["url"], info["number"], info["branch"]
        run.pr_fake = bool(info["fake"])
        run.files_changed = len(files)
        run.emit("pr", {"url": info["url"], "branch": info["branch"], "number": info["number"],
                        "fake": info["fake"], **({"updated": True} if info.get("updated") else {})})
        reg.save(run)
        return pr_info(run)


def pr_info(run: Any) -> dict[str, Any]:
    return {"url": run.pr_url, "branch": run.pr_branch, "number": run.pr_number, "fake": run.pr_fake}
