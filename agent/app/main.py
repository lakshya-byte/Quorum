"""PatchLoop agent HTTP API. Internal service: the Go backend is the only caller."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.bugs import BUGS, get_bug
from app.config import Settings, load_settings
from app.github_pr import NEBIUS_LABEL, open_pr
from app.runs import Run, RunRegistry
from app.search import is_solved

log = logging.getLogger(__name__)

SSE_POLL = 0.2
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


class RunRequest(BaseModel):
    bug_id: str
    user_id: str | None = None
    model_override: str | None = None
    replay: bool = False


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def stream_events(run: Run, request: Request) -> AsyncIterator[str]:
    sent = 0
    while True:
        while sent < len(run.events):
            yield sse(run.events[sent])
            sent += 1
        if run.finished or await request.is_disconnected():
            break
        await asyncio.sleep(SSE_POLL)
    yield sse({"type": "end"})


def build_router(registry: RunRegistry) -> APIRouter:
    router = APIRouter()

    def require_run(run_id: str) -> Run:
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return run

    @router.get("/bugs")
    async def list_bugs() -> list[dict[str, str]]:
        return [{"id": b["id"], "title": b["title"], "issue": b["issue"]} for b in BUGS.values()]

    @router.post("/runs")
    async def create_run(body: RunRequest) -> dict[str, Any]:
        bug = get_bug(body.bug_id)
        if bug is None:
            raise HTTPException(404, f"unknown bug_id {body.bug_id!r}")
        if body.replay:
            source = registry.best_replay(bug["id"])
            if source is not None:
                run = registry.start_replay(source, body.user_id)
                return {"run_id": run.run_id, "mode": run.mode, "replay_of": source.run_id}
            run = registry.start(bug, body.user_id, mode="fake")
        else:
            run = registry.start(bug, body.user_id, body.model_override)
        return {"run_id": run.run_id, "mode": run.mode}

    @router.get("/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request) -> StreamingResponse:
        run = require_run(run_id)
        return StreamingResponse(stream_events(run, request), media_type="text/event-stream", headers=SSE_HEADERS)

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        return require_run(run_id).public()

    @router.post("/runs/{run_id}/pr")
    async def create_pr(run_id: str) -> dict[str, str]:
        run = require_run(run_id)
        done = run.done_event()
        best = done.get("best")
        if not done.get("solved") or not best or not is_solved(best):
            raise HTTPException(400, "run is not solved")
        bug = get_bug(run.bug_id)
        if bug is None:
            raise HTTPException(404, "bug not found")
        label = NEBIUS_LABEL if run.mode in ("live", "replay") else "an isolated local sandbox"
        try:
            url = await asyncio.to_thread(open_pr, bug, best, registry.settings, label)
        except Exception as exc:
            log.warning("opening PR failed: %s", type(exc).__name__)
            raise HTTPException(502, f"could not open pull request: {type(exc).__name__}") from exc
        return {"url": url}

    @router.get("/replays")
    async def list_replays() -> list[dict[str, Any]]:
        return registry.saved_replays()

    @router.post("/replays/{run_id}")
    async def start_replay(run_id: str) -> dict[str, Any]:
        source = registry.load(run_id)
        if source is None or source.mode not in ("hybrid", "live") or not source.done_event().get("solved"):
            raise HTTPException(404, "saved run not found")
        run = registry.start_replay(source)
        return {"run_id": run.run_id, "mode": run.mode, "replay_of": source.run_id}

    return router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    registry = RunRegistry(settings)

    async def check_secret(x_agent_secret: str = Header(default="")) -> None:
        if not hmac.compare_digest(x_agent_secret.encode(), settings.shared_secret.encode()):
            raise HTTPException(401, "invalid agent secret")

    app = FastAPI(title="PatchLoop agent", version="0.1.0")
    app.state.registry = registry

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode}

    app.include_router(build_router(registry), dependencies=[Depends(check_secret)])
    return app


app = create_app()
