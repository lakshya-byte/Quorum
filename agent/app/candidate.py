"""One candidate, the moment it arrives: policy gate -> sandbox tests -> security scan -> score.

Shared by both engines so every node carries the same fields:
{id, parent, depth, idea, strategy, code, output, passed, total, score, model, latency_ms, tokens,
 policy: {ok, reasons}, security: {ok, new_findings}}
"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any

from app.bugs import Bug, files_for
from app.policy import DEFAULT_MAX_DIFF, check_candidate
from app.sandbox import Sandbox
from app.scoring import parse_unittest, score
from app.security import Finding, security_verdict
from app.telemetry import span

Node = dict[str, Any]
CACHE_MAX = 512

_results: OrderedDict[str, tuple[int, str, list[Finding] | None]] = OrderedDict()
_baselines: dict[tuple[str, str], list[Finding] | None] = {}


def _key(sandbox: Sandbox, files: dict[str, str]) -> str:
    h = hashlib.sha256(type(sandbox).__name__.encode())
    for name in sorted(files):
        h.update(b"\0" + name.encode() + b"\0" + files[name].encode())
    return h.hexdigest()


def clear_caches() -> None:
    _results.clear()
    _baselines.clear()


async def cached_check(sandbox: Sandbox, bug: Bug, code: str, timeout: int) -> tuple[int, str, list[Finding] | None]:
    """Tests + scan, cached by sha256(code + tests) so identical candidates are never re-run."""
    files = files_for(bug, code)
    key = _key(sandbox, files)
    if key in _results:
        _results.move_to_end(key)
        return _results[key]
    with span("sandbox.check", group="PatchLoop/Sandbox"):
        result = await sandbox.check(files, bug["target"], timeout)
    if not result[1].startswith("SANDBOX_ERROR"):
        _results[key] = result
        if len(_results) > CACHE_MAX:
            _results.popitem(last=False)
    return result


async def baseline_findings(sandbox: Sandbox, bug: Bug) -> list[Finding] | None:
    key = (type(sandbox).__name__, bug["id"])
    if key not in _baselines:
        with span("sandbox.scan_baseline", group="PatchLoop/Sandbox"):
            _baselines[key] = await sandbox.scan(bug["target"], bug["buggy"])
    return _baselines[key]


def gate_ok(node: Node) -> bool:
    return node.get("policy", {}).get("ok", True) and node.get("security", {}).get("ok", True)


def is_solved(node: Node) -> bool:
    if node.get("baseline"):  # repo runs: the untouched original is a reference, never a solution
        return False
    return node["total"] > 0 and node["passed"] == node["total"] and gate_ok(node)


def rank(node: Node) -> tuple[bool, float, int]:
    """Tests decide; score already prefers the smaller diff on ties; then the earlier node."""
    return is_solved(node), node["score"], -node["id"]


async def evaluate_candidate(
    bug: Bug,
    sandbox: Sandbox,
    *,
    node_id: int,
    parent: int | None,
    depth: int,
    idea: str,
    code: str,
    model: str,
    strategy: str = "",
    extra_files: dict[str, str] | None = None,
    timeout: int = 20,
    max_diff_lines: int = DEFAULT_MAX_DIFF,
    started: float | None = None,
    tokens: int = 0,
    skip_policy: bool = False,
    files: dict[str, str] | None = None,
) -> Node:
    """Build a fully evaluated node. `extra_files` are other files the candidate tried to write.
    Repo tasks (bug["repo"]) take the whole multi-file candidate in `files`."""
    if bug.get("repo"):
        from app.repo_eval import evaluate_repo_candidate

        return await evaluate_repo_candidate(
            bug, sandbox, node_id=node_id, parent=parent, depth=depth, idea=idea,
            files=files if files is not None else {bug["target"]: code, **(extra_files or {})}, model=model,
            strategy=strategy, timeout=timeout, max_diff_lines=max_diff_lines, started=started, tokens=tokens,
            skip_policy=skip_policy,
        )
    t0 = started if started is not None else time.monotonic()
    changed = {bug["target"]: code, **(extra_files or {})}
    if skip_policy:  # node 0: the original buggy code is the reference, not an AI candidate
        policy = {"ok": True, "reasons": []}
    else:
        with span("policy.check", group="PatchLoop/Gate"):
            policy = check_candidate(bug, changed, max_diff_lines=max_diff_lines).as_dict()
    security: dict[str, Any] = {"ok": True, "new_findings": []}
    if not code.strip():
        output, passed, total = "NO_CODE: the proposer returned no code block", 0, 0
    elif not policy["ok"]:
        output = "POLICY_BLOCKED (not run):\n" + "\n".join(f"- {r}" for r in policy["reasons"])
        passed, total = 0, 0
    else:
        # The harness always writes the ORIGINAL tests: only the target comes from the candidate.
        _, output, after = await cached_check(sandbox, bug, code, timeout)
        passed, total = parse_unittest(output)
        if skip_policy and code == bug["buggy"]:  # node 0's scan is the security baseline
            _baselines.setdefault((type(sandbox).__name__, bug["id"]), after)
        if not skip_policy:
            before = await baseline_findings(sandbox, bug)
            verdict = security_verdict(before, after)
            security = {"ok": verdict["ok"], "new_findings": verdict["new_findings"], "scanned": verdict["scanned"]}
    value = score(passed, total, bug["buggy"], code)
    if not policy["ok"] or not security["ok"]:
        value = 0.0
    return {
        "id": node_id, "parent": parent, "depth": depth, "idea": idea, "strategy": strategy,
        "code": code, "output": output, "passed": passed, "total": total,
        "score": round(value, 4), "model": model,
        "latency_ms": int((time.monotonic() - t0) * 1000), "tokens": tokens,
        "policy": policy, "security": security,
    }
