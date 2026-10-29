"""Turn unittest output into (passed, total) and a comparable score."""
from __future__ import annotations

import difflib
import re

_RAN = re.compile(r"^Ran (\d+) tests?", re.MULTILINE)
_FAILED = re.compile(r"^FAILED \(([^)]*)\)", re.MULTILINE)
_BROKEN = ("SyntaxError", "ImportError")

PATCH_PENALTY = 0.001
MAX_PENALISED_LINES = 50


def parse_unittest(output: str) -> tuple[int, int]:
    ran = _RAN.findall(output)
    total = int(ran[-1]) if ran else 0
    if total == 0 or any(marker in output for marker in _BROKEN):
        return 0, total
    failed_line = _FAILED.findall(output)
    failed = sum(int(n) for n in re.findall(r"\d+", failed_line[-1])) if failed_line else 0
    return max(0, total - failed), total


def changed_lines(old: str, new: str) -> int:
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
    return sum(
        1 for line in diff
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def score(passed: int, total: int, old_code: str, new_code: str) -> float:
    if total == 0:
        return 0.0
    penalty = PATCH_PENALTY * min(changed_lines(old_code, new_code), MAX_PENALISED_LINES)
    return max(0.0, passed / total - penalty)


_PYTEST_COUNT = re.compile(r"(\d+) (passed|failed|errors?)\b")
_JEST = re.compile(r"Tests:\s+(?:(\d+) failed,\s*)?(?:(\d+) passed,\s*)?(\d+) total")
_MOCHA_PASS = re.compile(r"^\s*(\d+) passing", re.MULTILINE)
_MOCHA_FAIL = re.compile(r"^\s*(\d+) failing", re.MULTILINE)
_TAP = re.compile(r"^# (pass|fail) (\d+)", re.MULTILINE)
_GO_PKG = re.compile(r"^(ok|FAIL)\s+\S+", re.MULTILINE)


def parse_results(output: str, exit_code: int = 0, language: str = "python") -> tuple[int, int]:
    """(passed, total) for unittest/pytest (solid) and Node/Go (best effort: falls back to the exit code)."""
    if language == "python":
        if _RAN.search(output):
            return parse_unittest(output)
        counts = {"passed": 0, "failed": 0, "error": 0}
        last = output.strip().splitlines()[-1] if output.strip() else ""
        for n, kind in _PYTEST_COUNT.findall(last):
            counts["error" if kind.startswith("error") else kind] += int(n)
        total = sum(counts.values())
        if total and not any(m in output for m in ("SyntaxError", "ImportError", "ModuleNotFoundError")):
            return counts["passed"], total
        return 0, total
    if language == "node":
        m = _JEST.search(output)
        if m:
            return int(m.group(2) or 0), int(m.group(3))
        p, f = _MOCHA_PASS.search(output), _MOCHA_FAIL.search(output)
        if p or f:
            ok = int(p.group(1)) if p else 0
            return ok, ok + (int(f.group(1)) if f else 0)
        tap = dict(_TAP.findall(output))
        if tap:
            return int(tap.get("pass", 0)), int(tap.get("pass", 0)) + int(tap.get("fail", 0))
    if language == "go":
        pkgs = _GO_PKG.findall(output)
        if pkgs:
            return pkgs.count("ok"), len(pkgs)
    if output.strip() in ("TIMEOUT", "") and exit_code != 0:
        return 0, 0
    return (1, 1) if exit_code == 0 else (0, 1)
