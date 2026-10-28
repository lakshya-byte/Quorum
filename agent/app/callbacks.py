"""Report finished runs to the Go backend."""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

CALLBACK_TIMEOUT = 5.0


async def post_completion(base_url: str, secret: str, payload: dict[str, Any]) -> bool:
    """POST the final payload. Failures are logged and swallowed; returns success."""
    if not base_url:
        return False
    url = f"{base_url}/internal/runs/{payload['run_id']}/complete"
    try:
        async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers={"X-Agent-Secret": secret})
        resp.raise_for_status()
        return True
    except Exception as exc:
        log.warning("backend callback for run %s failed: %s", payload["run_id"], type(exc).__name__)
        return False
