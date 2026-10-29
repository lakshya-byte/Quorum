"""Security stage: bandit before/after; new medium+ findings block a candidate."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BLOCKING_SEVERITIES = {"MEDIUM", "HIGH"}
BANDIT_TIMEOUT = 20
Finding = dict[str, Any]


def bandit_available() -> bool:
    return importlib.util.find_spec("bandit") is not None


def parse_bandit_json(text: str) -> list[Finding] | None:
    """Findings from `bandit -f json` output, or None if the output is not bandit JSON."""
    start = text.find("{")
    if start < 0:
        return None
    try:
        data = json.loads(text[start:])
    except ValueError:
        return None
    return [
        {
            "test_id": r.get("test_id", ""),
            "severity": str(r.get("issue_severity", "")).upper(),
            "confidence": str(r.get("issue_confidence", "")).upper(),
            "line": r.get("line_number"),
            "text": r.get("issue_text", ""),
        }
        for r in data.get("results", [])
    ]


def new_findings(before: list[Finding] | None, after: list[Finding] | None) -> list[Finding]:
    """Medium+ findings present after the change and not before (multiset on test id + text)."""
    if not after:
        return []
    seen = Counter((f["test_id"], f["text"]) for f in (before or []))
    fresh = []
    for f in after:
        key = (f["test_id"], f["text"])
        if seen[key] > 0:
            seen[key] -= 1
            continue
        if f["severity"] in BLOCKING_SEVERITIES:
            fresh.append(f)
    return fresh


def security_verdict(before: list[Finding] | None, after: list[Finding] | None) -> dict[str, Any]:
    """{ok, new_findings, scanned}. Unscanned (bandit missing) counts as ok but says so."""
    if after is None:
        return {"ok": True, "new_findings": [], "scanned": False}
    fresh = new_findings(before, after)
    return {"ok": not fresh, "new_findings": fresh, "scanned": True}


async def bandit_local(filename: str, code: str) -> list[Finding] | None:
    """Run bandit on one file in a temp dir. None if bandit is not installed or fails."""
    if not bandit_available():
        return None
    with tempfile.TemporaryDirectory(prefix="patchloop-bandit-") as tmp:
        path = Path(tmp, filename)
        path.write_text(code, encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "bandit", "-f", "json", "-q", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", "")},
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), BANDIT_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return None
        except asyncio.CancelledError:
            proc.kill()
            raise
    return parse_bandit_json(out.decode("utf-8", errors="replace"))
