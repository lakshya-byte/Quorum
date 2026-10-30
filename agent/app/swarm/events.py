"""Event helpers: secret redaction, compact payloads (contract section 4) and replay compaction."""
from __future__ import annotations

import re
from typing import Any

from app.swarm.types import Emit

TOOL_NOTE_MAX = 200
DIFF_MAX = 20_000
DETAIL_MAX = 500
REPLAY_TOOL_KEEP = 60

# generic credential shapes: GitHub tokens, OpenAI-style keys, AWS ids, bearer headers, PEM blocks
_SECRET_RES = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.DOTALL),
]
SECRET_LIKE = [
    *_SECRET_RES,
    re.compile(r"""(?i)\b(?:api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*['"][A-Za-z0-9_\-/+=]{16,}['"]"""),
]


class Redactor:
    """Scrubs the run's own credentials (exact strings) and common token shapes from any text or payload."""

    def __init__(self, secrets: list[str] | None = None) -> None:
        self.secrets = [s for s in (secrets or []) if s and len(s) >= 4]

    def text(self, value: str) -> str:
        out = value or ""
        for s in self.secrets:
            out = out.replace(s, "***")
        for rx in _SECRET_RES:
            out = rx.sub("***", out)
        return out

    def obj(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.obj(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.obj(v) for v in value]
        return value


def looks_secret(text: str) -> list[str]:
    """Secret-looking strings in `text` (for the `secrets` gate), shortened for display."""
    found = []
    for rx in SECRET_LIKE:
        for m in rx.finditer(text or ""):
            found.append(m.group(0)[:12] + "...")
    return found


class Hub:
    """The only way swarm code emits events: redacts, caps sizes, and counts what the UI needs."""

    def __init__(self, emit: Emit, redactor: Redactor) -> None:
        self._emit = emit
        self.red = redactor
        self.agents_spawned = 0
        self.denied = 0  # tool calls refused by the policy gate / command allow-list

    async def emit(self, kind: str, data: dict[str, Any]) -> None:
        await self._emit(kind, self.red.obj(data))

    async def agent(self, agent_id: str, role: str, status: str, *, unit_id: str | None = None,
                    variant: int | None = None, model: str = "", isolation: str = "local",
                    summary: str = "", tokens: int | None = None, steps: int | None = None) -> None:
        if status == "spawned":
            self.agents_spawned += 1
        data: dict[str, Any] = {"id": agent_id, "role": role, "unit_id": unit_id, "variant": variant,
                                "status": status, "model": model, "isolation": isolation}
        if summary:
            data["summary"] = summary[:300]
        if tokens is not None:
            data["tokens"] = tokens
        if steps is not None:
            data["steps"] = steps
        await self.emit("agent", data)

    async def tool(self, agent_id: str, name: str, target: str, ok: bool, ms: int, note: str = "") -> None:
        data: dict[str, Any] = {"agent_id": agent_id, "name": name, "ok": ok, "ms": ms}
        if target:
            data["target"] = target[:120]
        if note:
            data["note"] = " ".join(note.split())[:TOOL_NOTE_MAX]
        if note in ("policy denied", "command denied"):
            self.denied += 1
        await self.emit("tool", data)


def compact_events(events: list[dict[str, Any]], keep: int = REPLAY_TOOL_KEEP) -> list[dict[str, Any]]:
    """Replay/persistence view: only the most recent `keep` tool events per agent survive (contract section 4)."""
    counts: dict[str, int] = {}
    for e in events:
        if e["type"] == "tool":
            a = e["data"].get("agent_id", "")
            counts[a] = counts.get(a, 0) + 1
    seen: dict[str, int] = {}
    out = []
    for e in events:
        if e["type"] == "tool":
            a = e["data"].get("agent_id", "")
            seen[a] = seen.get(a, 0) + 1
            if counts[a] - seen[a] >= keep:
                continue
        out.append(e)
    return out
