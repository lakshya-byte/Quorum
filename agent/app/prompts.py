"""Prompt text for fix proposals."""
from __future__ import annotations

from app.bugs import Bug

SYSTEM_PROMPT = (
    "You are a careful senior engineer fixing a bug. You get a bug report, the current "
    "source file and the latest test output. Reply with exactly one sentence starting with "
    "`Idea:` describing your fix, then the COMPLETE corrected file in a single ```python "
    "fenced block. Change as little as possible. Do not edit or include the tests."
)

HINTS = (
    "Focus on boundaries and off-by-one errors.",
    "Focus on input validation and edge cases such as empty or out-of-range input.",
    "Re-read the tests carefully and rewrite the function to satisfy all of them.",
)

OUTPUT_TAIL = 1800


def hint_for(i: int) -> str:
    return HINTS[i % len(HINTS)]


def build_user_prompt(bug: Bug, code: str, test_output: str, i: int) -> str:
    tail = test_output[-OUTPUT_TAIL:] if test_output else "(no test output yet)"
    return (
        f"## Bug report\n{bug['issue']}\n\n"
        f"## Current {bug['target']}\n```python\n{code}\n```\n\n"
        f"## Latest test output (tail)\n```\n{tail}\n```\n\n"
        f"## Hint\n{hint_for(i)}\n"
    )
