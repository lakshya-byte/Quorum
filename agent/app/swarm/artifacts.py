"""Per-run artifact store (screenshots, logs, reports). Caps per contract: 5 MB each, 40 per run; text artifacts
pass a secret redactor before they are stored. Nothing here is written to disk."""
from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field

MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_ARTIFACTS = 40
KINDS = {"screenshot", "log", "report", "diff"}
MIME_OK = {"image/png", "image/jpeg", "image/svg+xml", "text/plain", "application/json", "text/html"}

_SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[REDACTED]"),
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE_?KEY)[A-Z0-9_]*)\s*[=:]\s*['\"]?[^\s'\"]{6,}"),
     r"\1=[REDACTED]"),
    (re.compile(r"(?i)\b(https?://[^/\s:@]+):[^/\s@]{3,}@"), r"\1:[REDACTED]@"),
]


def redact_text(text: str) -> str:
    for rx, repl in _SECRET_PATTERNS:
        text = rx.sub(repl, text)
    return text


@dataclass
class Artifact:
    id: str
    kind: str
    label: str
    phase: str = "n/a"
    viewport: str | None = None
    mime: str = "text/plain"
    size: int = 0

    def meta(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "phase": self.phase,
                "viewport": self.viewport, "mime": self.mime, "size": self.size}


@dataclass
class ArtifactStore:
    max_artifacts: int = MAX_ARTIFACTS
    max_bytes: int = MAX_ARTIFACT_BYTES
    _items: dict[str, Artifact] = field(default_factory=dict)
    _data: dict[str, bytes] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, kind: str, label: str, phase: str = "n/a", viewport: str | int | None = None,
            mime: str = "text/plain", data: bytes | str = b"") -> Artifact | None:
        """Store one artifact; returns None (never raises) when a cap or type rule rejects it."""
        if kind not in KINDS or mime not in MIME_OK:
            return None
        if isinstance(data, str):
            data = redact_text(data).encode("utf-8", errors="replace")
        elif mime.startswith("text/") or mime in ("application/json", "image/svg+xml"):
            data = redact_text(bytes(data).decode("utf-8", errors="replace")).encode("utf-8")
        if len(data) > self.max_bytes:
            if mime.startswith("text/"):
                data = data[-self.max_bytes:]
            else:
                return None
        with self._lock:
            if len(self._items) >= self.max_artifacts:
                return None
            art = Artifact(id=uuid.uuid4().hex[:12], kind=kind, label=label[:120], phase=phase,
                           viewport=str(viewport) if viewport is not None else None, mime=mime, size=len(data))
            self._items[art.id] = art
            self._data[art.id] = bytes(data)
        return art

    def list(self) -> list[Artifact]:
        with self._lock:
            return list(self._items.values())

    def get(self, artifact_id: str) -> tuple[Artifact, bytes] | None:
        with self._lock:
            art = self._items.get(artifact_id)
            return (art, self._data[artifact_id]) if art else None

    def bytes_of(self, artifact_id: str) -> bytes | None:
        got = self.get(artifact_id)
        return got[1] if got else None
