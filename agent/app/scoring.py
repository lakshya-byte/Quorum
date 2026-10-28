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
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )


def score(passed: int, total: int, old_code: str, new_code: str) -> float:
    if total == 0:
        return 0.0
    penalty = PATCH_PENALTY * min(changed_lines(old_code, new_code), MAX_PENALISED_LINES)
    return max(0.0, passed / total - penalty)
