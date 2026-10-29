"""Repo tasks as engine input: build the bug-like dict the graph engine already understands, and evaluate
multi-file candidates (policy on every path -> repo tests -> bandit on every changed file -> score)."""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import time
from collections import OrderedDict
from typing import Any

from app.policy import check_repo_candidate
from app.repo_detect import is_test_path
from app.repo_loader import RepoSnapshot
from app.scoring import PATCH_PENALTY, MAX_PENALISED_LINES, changed_lines, parse_results
from app.security import Finding, security_verdict
from app.telemetry import span

Node = dict[str, Any]
DIFF_CAP = 20_000
CACHE_MAX = 256
_results: OrderedDict[str, tuple[int, str]] = OrderedDict()
_baselines: dict[tuple[str, str, str], list[Finding] | None] = {}


def clear_caches() -> None:
    _results.clear()
    _baselines.clear()


def slugify(text: str, limit: int = 36) -> str:
    out, last = [], True
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
            last = False
        elif not last:
            out.append("-")
            last = True
    return ("".join(out).strip("-")[:limit].strip("-")) or "fix"


def build_repo_bug(
    snap: RepoSnapshot, task: str, located: list[str], run_id: str, reproducer_path: str = "",
    reproducer_text: str = "",
) -> dict[str, Any]:
    """The adapter: a repo task in the shape the graph engine expects (plus repo-only keys)."""
    sources = [p for p in located if p in snap.files and not is_test_path(p)]
    target = sources[0] if sources else ""
    fixes = snap.meta.get("fixes") if snap.demo else None
    return {
        "id": f"repo-{run_id[:8]}", "tier": "repo", "repo": True,
        "title": (task.strip().splitlines() or ["repo task"])[0][:100],
        "issue": task, "target": target, "buggy": snap.files.get(target, ""),
        "tests": reproducer_text, "reproducer_path": reproducer_path if reproducer_text else "",
        "files": snap.files, "located": sources, "test_command": snap.test_command, "language": snap.language,
        "full_name": snap.full_name, "branch": snap.branch, "checkpoint": None, "setup": "",
        "fake": fixes,
    }


def test_files_of(bug: dict[str, Any]) -> list[str]:
    return sorted(p for p in bug["files"] if is_test_path(p))


def effective_changes(bug: dict[str, Any], files: dict[str, str]) -> dict[str, str]:
    originals = bug["files"]
    return {p: c for p, c in files.items() if originals.get(p) != c or p == bug.get("reproducer_path")}


def unified_diff(bug: dict[str, Any], changed: dict[str, str], cap: int = DIFF_CAP) -> str:
    chunks = []
    for path in sorted(changed):
        old = bug["files"].get(path)
        a = (old or "").splitlines(keepends=True)
        b = changed[path].splitlines(keepends=True)
        head = f"diff --git a/{path} b/{path}\n" + ("new file mode 100644\n" if old is None else "")
        body = "".join(difflib.unified_diff(a, b, "/dev/null" if old is None else f"a/{path}", f"b/{path}"))
        chunks.append(head + body)
        if sum(len(c) for c in chunks) > cap:
            break
    return "".join(chunks)[:cap]


def _overlay(bug: dict[str, Any], changed: dict[str, str]) -> dict[str, str]:
    files = dict(changed)
    if bug.get("reproducer_path"):
        files[bug["reproducer_path"]] = bug["tests"]
    return files


def _key(bug: dict[str, Any], overlay: dict[str, str]) -> str:
    h = hashlib.sha256(bug["id"].encode())
    for name in sorted(overlay):
        h.update(b"\0" + name.encode() + b"\0" + overlay[name].encode())
    return h.hexdigest()


async def run_tests(bug: dict[str, Any], sandbox: Any, changed: dict[str, str], timeout: int) -> tuple[int, str]:
    overlay = _overlay(bug, changed)
    key = _key(bug, overlay)
    if key in _results:
        _results.move_to_end(key)
        return _results[key]
    with span("sandbox.repo_check", group="PatchLoop/Sandbox"):
        if bug.get("checkpoint") is not None:
            result = await sandbox.run_repo(overlay, bug["test_command"], timeout, base=bug["checkpoint"],
                                            setup=bug.get("setup", ""))
        else:
            result = await sandbox.run_repo({**bug["files"], **overlay}, bug["test_command"], timeout,
                                            setup=bug.get("setup", ""))
    if not result[1].startswith("SANDBOX_ERROR"):
        _results[key] = result
        if len(_results) > CACHE_MAX:
            _results.popitem(last=False)
    return result


async def _baseline_scan(bug: dict[str, Any], sandbox: Any, path: str) -> list[Finding] | None:
    key = (type(sandbox).__name__, bug["id"], path)
    if key not in _baselines:
        old = bug["files"].get(path)
        _baselines[key] = await sandbox.scan(path, old) if old is not None else []
    return _baselines[key]


async def scan_changed(bug: dict[str, Any], sandbox: Any, changed: dict[str, str]) -> dict[str, Any]:
    """Bandit on EVERY changed Python file, compared with the original of that same file."""
    paths = [p for p in sorted(changed) if p.endswith(".py") and not is_test_path(p)]
    fresh: list[dict[str, Any]] = []
    scanned = bool(paths)
    for path in paths:
        before = await _baseline_scan(bug, sandbox, path)
        after = await sandbox.scan(path, changed[path])
        verdict = security_verdict(before, after)
        scanned = scanned and verdict["scanned"]
        fresh += [{**f, "file": path} for f in verdict["new_findings"]]
    return {"ok": not fresh, "new_findings": fresh, "scanned": scanned, "files": paths}


def repo_score(passed: int, total: int, bug: dict[str, Any], changed: dict[str, str]) -> float:
    if total == 0:
        return 0.0
    lines = sum(changed_lines(bug["files"].get(p, ""), c) for p, c in changed.items()
                if p != bug.get("reproducer_path"))
    return max(0.0, passed / total - PATCH_PENALTY * min(lines, MAX_PENALISED_LINES))


async def evaluate_repo_candidate(
    bug: dict[str, Any], sandbox: Any, *, node_id: int, parent: int | None, depth: int, idea: str,
    files: dict[str, str], model: str, strategy: str = "", timeout: int = 20, max_diff_lines: int = 60,
    started: float | None = None, tokens: int = 0, skip_policy: bool = False,
) -> Node:
    t0 = started if started is not None else time.monotonic()
    changed = {} if skip_policy else effective_changes(bug, files)
    changed.pop(bug.get("reproducer_path") or "\0", None)  # the harness always supplies the reproducer itself
    # a candidate that rewrites the reproducer differently is a policy violation, not a silent overwrite
    if not skip_policy and bug.get("reproducer_path") in files and files[bug["reproducer_path"]] != bug["tests"]:
        changed[bug["reproducer_path"]] = files[bug["reproducer_path"]]
    if skip_policy:
        policy = {"ok": True, "reasons": []}
    else:
        with span("policy.check", group="PatchLoop/Gate"):
            policy = check_repo_candidate(bug, changed, max_diff_lines=max_diff_lines).as_dict()
    security: dict[str, Any] = {"ok": True, "new_findings": [], "scanned": False}
    if not skip_policy and not changed:
        output, passed, total = "NO_CODE: the proposer returned no file changes", 0, 0
    elif not policy["ok"]:
        output = "POLICY_BLOCKED (not run):\n" + "\n".join(f"- {r}" for r in policy["reasons"])
        passed, total = 0, 0
    else:
        code, output = await run_tests(bug, sandbox, changed, timeout)
        passed, total = parse_results(output, code, bug["language"])
        if not skip_policy:
            security = await scan_changed(bug, sandbox, changed)
    value = repo_score(passed, total, bug, changed)
    if not policy["ok"] or not security["ok"]:
        value = 0.0
    primary = bug["target"] if bug["target"] in changed else (next(iter(changed), bug["target"]))
    return {
        "id": node_id, "parent": parent, "depth": depth, "idea": idea, "strategy": strategy,
        "code": changed.get(primary, bug["buggy"]), "output": output, "passed": passed, "total": total,
        "score": round(value, 4), "model": model, "latency_ms": int((time.monotonic() - t0) * 1000),
        "tokens": tokens, "policy": policy, "security": security,
        "files": dict(changed), "diff": unified_diff(bug, changed) if changed else "",
        **({"baseline": True} if skip_policy else {}),
    }


async def gather_baseline_scan(bug: dict[str, Any], sandbox: Any) -> None:
    await asyncio.gather(*[_baseline_scan(bug, sandbox, p) for p in bug["located"] if p.endswith(".py")])
