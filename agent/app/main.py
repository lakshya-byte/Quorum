"""PatchLoop agent HTTP API. Internal service: the Go backend is the only caller."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.bugs import BUGS, get_bug
from app.config import Settings, load_settings
from app.github_pr import open_pr
from app.guard import GuardService
from app.runs import Run, RunRegistry
from app.search import is_solved
from app.telemetry import (
    new_trace_id, parse_traceparent, setup_langsmith, setup_logging, setup_newrelic, trace_id_var,
)

log = logging.getLogger(__name__)

SSE_KEEPALIVE = 10.0
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


class RunRequest(BaseModel):
    bug_id: str
    user_id: str | None = None
    engine: Literal["graph", "loop"] | None = None
    model_override: str | None = None
    replay: bool = False


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def stream_events(run: Run, request: Request) -> AsyncIterator[str]:
    """Push each event the moment it is emitted (event-driven, no polling delay)."""
    sent = 0
    while True:
        signal = run._signal  # grab before reading so no event can slip between check and wait
        while sent < len(run.events):
            yield sse(run.events[sent])
            sent += 1
        if run.finished or await request.is_disconnected():
            break
        await run.wait_change(signal, SSE_KEEPALIVE)
    yield sse({"type": "end"})


def trace_from(request: Request) -> tuple[str, dict[str, str]]:
    tp = request.headers.get("traceparent")
    trace_id = parse_traceparent(tp) or new_trace_id()
    headers = {"traceparent": tp} if tp and parse_traceparent(tp) else {}
    if headers and request.headers.get("tracestate"):
        headers["tracestate"] = request.headers["tracestate"]
    return trace_id, headers


def build_router(registry: RunRegistry) -> APIRouter:
    router = APIRouter()

    def require_run(run_id: str) -> Run:
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return run

    @router.get("/bugs")
    async def list_bugs() -> list[dict[str, str]]:
        return [{"id": b["id"], "title": b["title"], "issue": b["issue"], "tier": b.get("tier", "easy")}
                for b in BUGS.values()]

    @router.post("/runs")
    async def create_run(body: RunRequest, request: Request) -> dict[str, Any]:
        bug = get_bug(body.bug_id)
        if bug is None:
            raise HTTPException(404, f"unknown bug_id {body.bug_id!r}")
        trace_id, trace_headers = trace_from(request)
        trace_id_var.set(trace_id)
        if body.replay:
            source = registry.best_replay(bug["id"])
            if source is not None:
                run = registry.start_replay(source, body.user_id, trace_id)
                return {"run_id": run.run_id, "mode": run.mode, "engine": run.engine, "replay_of": source.run_id,
                        "trace_id": trace_id}
            run = registry.start(bug, body.user_id, mode="fake", engine=body.engine,
                                 trace_id=trace_id, trace_headers=trace_headers)
        else:
            run = registry.start(bug, body.user_id, body.model_override, engine=body.engine,
                                 trace_id=trace_id, trace_headers=trace_headers)
        log.info("run started bug=%s mode=%s engine=%s", bug["id"], run.mode, run.engine,
                 extra={"run_id": run.run_id, "trace_id": trace_id})
        return {"run_id": run.run_id, "mode": run.mode, "engine": run.engine, "trace_id": trace_id}

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
        if run.pr_url:
            return {"url": run.pr_url}
        done = run.done_event()
        best = done.get("best")
        if not done.get("solved") or not best or not is_solved(best):
            raise HTTPException(400, "run is not solved")
        bug = get_bug(run.bug_id)
        if bug is None:
            raise HTTPException(404, "bug not found")
        if not registry.settings.github_token or not registry.settings.github_repo:
            raise HTTPException(503, "pull requests are not configured: set GITHUB_TOKEN and GITHUB_REPO on the agent")
        label = "an isolated Nebius Sandbox" if run.mode in ("live", "replay") else "an isolated local sandbox"
        draft = run.pr_draft if run.pr_draft and run.pr_draft.get("guard") == "pass" else None
        try:
            url = await asyncio.to_thread(open_pr, bug, best, registry.settings, label, draft)
        except Exception as exc:
            log.warning("opening PR failed: %s", type(exc).__name__, extra={"run_id": run_id})
            raise HTTPException(502, f"could not open pull request: {type(exc).__name__}") from exc
        run.pr_url = url
        run.emit("pr", {"url": url})
        registry.save(run)
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
        return {"run_id": run.run_id, "mode": run.mode, "engine": run.engine, "replay_of": source.run_id}

    return router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    setup_logging()
    langsmith_on = setup_langsmith(settings.langsmith_api_key, settings.langsmith_project)
    newrelic_on = setup_newrelic(settings.new_relic_license_key)
    guard = GuardService(settings)
    registry = RunRegistry(settings, guard)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await guard.startup()  # probe backend, build rails once, warm up
        prewarm = None
        if settings.mode == "live" and settings.sandbox_ready:
            prewarm = asyncio.create_task(registry.nebius().prepare())  # tool image off the request path
        if not settings.shared_secret:
            log.error("AGENT_SHARED_SECRET is not set: every route except /health will answer 401")
        log.info("agent ready mode=%s engine=%s guard=%s langsmith=%s newrelic=%s",
                 settings.mode, settings.engine, guard.backend, langsmith_on, newrelic_on)
        yield
        if prewarm and not prewarm.done():
            prewarm.cancel()

    async def check_secret(x_agent_secret: str = Header(default="")) -> None:
        if not settings.shared_secret or not hmac.compare_digest(x_agent_secret.encode(), settings.shared_secret.encode()):
            raise HTTPException(401, "invalid agent secret")

    app = FastAPI(title="PatchLoop agent", version="0.2.0", lifespan=lifespan)
    app.state.registry = registry

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "mode": settings.mode, "engine": settings.engine, "guard_backend": guard.backend,
                "langsmith": langsmith_on, "newrelic": newrelic_on}

    app.include_router(build_router(registry), dependencies=[Depends(check_secret)])
    return app


app = create_app()
