"""PatchLoop agent HTTP API. Internal service: the Go backend is the only caller."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, SecretStr, model_validator

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


class RepoRef(BaseModel):
    full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
    branch: str = Field(default="main", pattern=r"^[A-Za-z0-9_./-]{1,100}$")

    @model_validator(mode="after")
    def no_dot_segments(self) -> "RepoRef":
        parts = self.full_name.split("/") + self.branch.split("/")
        if any(p in (".", "..", "") for p in parts) or self.branch.endswith(".lock"):
            raise ValueError("invalid repository or branch name")
        return self


class FollowupBody(BaseModel):
    pr_branch: str = Field(pattern=r"^patchloop/[A-Za-z0-9_./-]{1,150}$")
    pr_number: int = Field(ge=0)
    message: str = Field(min_length=1, max_length=4000)
    previous_files: dict[str, str] = Field(default_factory=dict)


class RepoRunRequest(BaseModel):
    """POST /repo-runs. `github_token` is a per-run credential: SecretStr keeps it out of reprs and logs."""

    task: str = Field(min_length=1, max_length=4000)
    repo: RepoRef
    github_token: SecretStr | None = None
    user_id: str | None = None
    engine: Literal["graph", "loop"] | None = None
    auto_pr: bool = True
    run_url: str = Field(default="", max_length=500, pattern=r"^(https?://\S*)?$")
    followup: FollowupBody | None = None
    source: Literal["web", "cli", "slack", "github", "api"] = "api"
    issue_ref: int | None = Field(default=None, ge=1)
    # contract v3 (swarm)
    task_type: TASK_TYPES = "auto"
    strict: list[str] = Field(default_factory=list, max_length=20)
    limits: LimitsBody | None = None
    answers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_swarm_fields(self) -> "RepoRunRequest":
        import re

        if any(not re.match(ID_PATTERN, x) for x in self.strict):
            raise ValueError("strict entries must be criterion ids ([A-Za-z0-9_.-], max 60 chars)")
        if len(self.answers) > 10 or any(not re.match(ID_PATTERN, k) or len(v) > 2000 for k, v in self.answers.items()):
            raise ValueError("answers: at most 10 entries, ids [A-Za-z0-9_.-], values <= 2000 chars")
        return self


class LimitsBody(BaseModel):
    """User-requested run limits. They are only ever LOWERED by the env caps (SWARM_MAX_*), never raised."""

    max_workers: int | None = Field(default=None, ge=1, le=1000)
    max_tokens: int | None = Field(default=None, ge=1000, le=100_000_000)
    max_wall_s: float | None = Field(default=None, ge=1, le=86_400)


TASK_TYPES = Literal["auto", "bugfix", "feature", "refactor", "ui", "tests", "perf", "deps", "docs", "migration", "other"]
ID_PATTERN = r"^[A-Za-z0-9_.-]{1,60}$"


class PRRequest(BaseModel):
    github_token: SecretStr | None = None


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

    @router.get("/demo-repos")
    async def demo_repos() -> list[dict[str, Any]]:
        from app.repo_loader import list_demo_repos

        return list_demo_repos()

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

    @router.post("/repo-runs")
    async def create_repo_run(body: RepoRunRequest, request: Request) -> dict[str, Any]:
        from app.repo_flow import RepoSpec, resolve_demo
        from app.repo_loader import demo_names

        fake = registry.settings.mode == "fake"
        if body.repo.full_name.startswith("demo/") and resolve_demo(body.repo.full_name, fake) is None:
            raise HTTPException(404, f"unknown demo repo; available: {', '.join('demo/' + n for n in demo_names())}")
        trace_id, trace_headers = trace_from(request)
        trace_id_var.set(trace_id)
        fu = body.followup
        spec = RepoSpec(
            task=body.task, full_name=body.repo.full_name, branch=body.repo.branch,
            token=body.github_token.get_secret_value() if body.github_token else "", auto_pr=body.auto_pr,
            user_id=body.user_id, engine=body.engine, run_url=body.run_url, source=body.source,
            issue_ref=body.issue_ref, followup=fu.model_dump() if fu else None,
            task_type=body.task_type, strict=list(body.strict),
            limits=body.limits.model_dump(exclude_none=True) if body.limits else {}, answers=dict(body.answers),
        )
        run = registry.start_repo(spec, trace_id, trace_headers)
        log.info("repo run started repo=%s source=%s mode=%s", run.repo, run.source, run.mode,
                 extra={"run_id": run.run_id, "trace_id": trace_id})
        return {"run_id": run.run_id, "mode": run.mode, "engine": run.engine, "trace_id": trace_id}

    @router.get("/runs/{run_id}/artifacts")
    async def list_artifacts(run_id: str) -> list[dict[str, Any]]:
        from app.swarm.artifacts_api import artifact_meta, store_items

        run = require_run(run_id)
        return [artifact_meta(a, run.artifact_store) for a in store_items(run.artifact_store)]

    @router.get("/runs/{run_id}/artifacts/{artifact_id}")
    async def get_artifact(run_id: str, artifact_id: str) -> Response:
        from app.swarm.artifacts_api import artifact_response

        run = require_run(run_id)
        return artifact_response(run.artifact_store, artifact_id, [run._token])

    @router.post("/runs/{run_id}/pr")
    async def create_pr(run_id: str, body: PRRequest | None = None) -> dict[str, Any]:
        run = require_run(run_id)
        if run.kind == "repo":
            from app.repo_flow import PRError, open_run_pr, pr_info

            if run.pr_url:
                return pr_info(run)
            token = body.github_token.get_secret_value() if body and body.github_token else ""
            try:
                return await open_run_pr(registry, run, token)
            except PRError as exc:
                code = 400 if "not solved" in str(exc) or "token is required" in str(exc) else 502
                raise HTTPException(code, str(exc)) from None
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
