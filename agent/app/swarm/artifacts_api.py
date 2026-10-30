"""Serving run artifacts (screenshots, logs, reports) from builder B's ArtifactStore: GET /runs/{id}/artifacts[/{artifact_id}].

Guarantees (contract section 3): at most 40 artifacts and 5 MB each; only an allow-list of media types; text content
passes the redactor again before it leaves the process; responses are `nosniff` with a sandbox CSP.
The store is read through duck-typing: items need id/kind/label/phase/viewport/mime and bytes via `.data`
(or `.read()`); the store needs list() and get(id).
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from fastapi.responses import Response

from app.swarm.events import Redactor

MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_ARTIFACTS = 40
ALLOWED_MIME = {"image/png", "image/jpeg", "image/svg+xml", "text/plain", "text/html", "application/json"}
TEXT_MIME = {"text/plain", "text/html", "application/json", "image/svg+xml"}
ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def store_items(store: Any) -> list[Any]:
    if store is None:
        return []
    try:
        return list(store.list())[:MAX_ARTIFACTS]
    except Exception:
        return []


def _data(a: Any, store: Any = None) -> bytes:
    raw = getattr(a, "data", None)
    if raw is None and store is not None:
        for name in ("bytes_of", "read"):  # builder B's ArtifactStore.bytes_of(id) / get(id) -> (Artifact, bytes)
            fn = getattr(store, name, None)
            if callable(fn):
                try:
                    raw = fn(a.id)
                except Exception:
                    raw = None
                if raw is not None:
                    break
        if raw is None and callable(getattr(store, "get", None)):
            got = store.get(a.id)
            raw = got[1] if isinstance(got, (tuple, list)) and len(got) > 1 else getattr(got, "data", None)
    if raw is None and callable(getattr(a, "read", None)):
        raw = a.read()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return bytes(raw or b"")


def artifact_meta(a: Any, store: Any = None) -> dict[str, Any]:
    size = getattr(a, "size", None)
    return {"id": str(a.id), "kind": getattr(a, "kind", "log"), "label": str(getattr(a, "label", ""))[:120],
            "phase": getattr(a, "phase", "n/a") or "n/a", "viewport": getattr(a, "viewport", None),
            "mime": getattr(a, "mime", "text/plain"), "size": int(size if size is not None else len(_data(a, store)))}


def artifact_response(store: Any, artifact_id: str, secrets: list[str] | None = None) -> Response:
    if store is None or not ID_RE.match(artifact_id):
        raise HTTPException(404, "artifact not found")
    items = store_items(store)
    a = next((x for x in items if str(x.id) == artifact_id), None)
    if a is None:
        raise HTTPException(404, "artifact not found")
    mime = str(getattr(a, "mime", "text/plain")).split(";")[0].strip().lower()
    if mime not in ALLOWED_MIME:
        raise HTTPException(415, "unsupported artifact type")
    data = _data(a, store)
    if len(data) > MAX_ARTIFACT_BYTES:
        raise HTTPException(413, "artifact too large")
    if mime in TEXT_MIME:
        data = Redactor(secrets).text(data.decode("utf-8", errors="replace")).encode("utf-8")
    return Response(content=data, media_type=mime, headers={
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
        "Cache-Control": "private, max-age=60", "Content-Disposition": f'inline; filename="{artifact_id}"'})
