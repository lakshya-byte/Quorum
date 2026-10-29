"""In-memory run registry: starts runs (graph or loop engine), logs events, persists finished runs,
replays saved ones, reports to the backend and to New Relic."""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents import FakeTeam, LiveTeam
from app.bugs import Bug
from app.callbacks import post_completion
from app.config import LOCAL_TEST_TIMEOUT, SANDBOX_TEST_TIMEOUT, Settings
from app.graph_engine import BudgetExceeded, GraphCtx, run_graph
from app.guard import GuardService
from app.llm import make_client
from app.proposers import model_for, new_usage, propose_fake, propose_live
from app.sandbox import LocalSandbox, NebiusSandbox, Sandbox
from app.search import SearchConfig, run_search
from app.telemetry import background_run, record_event, run_id_var, trace_id_var

log = logging.getLogger(__name__)

REPLAY_PACING = 0.3
REAL_MODES = ("hybrid", "live")
REPLAYED_TYPES = ("guard", "triage", "round", "node", "critic", "done", "error")


@dataclass
class Run:
    run_id: str
    bug_id: str
    mode: str
    engine: str = "graph"
    user_id: str | None = None
    model_override: str | None = None
    replay_of: str | None = None
    status: str = "running"  # running | done | error | blocked | budget
    created_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str = ""
    trace_headers: dict[str, str] = field(default_factory=dict)
    pr_draft: dict[str, Any] | None = None
    pr_url: str | None = None
    t0: float = field(default_factory=time.monotonic)
    ttfn_ms: int | None = None
    latency_ms: int | None = None
    _signal: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def finished(self) -> bool:
        return self.status != "running"

    def _notify(self) -> None:
        sig, self._signal = self._signal, asyncio.Event()
        sig.set()

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        """Append an event and wake streamers immediately (no polling on the stream path)."""
        elapsed = int((time.monotonic() - self.t0) * 1000)
        if kind == "node" and self.ttfn_ms is None:
            self.ttfn_ms = elapsed
        if kind == "done":
            data = {**data, "latency_ms": data.get("latency_ms", elapsed),
                    "time_to_first_node_ms": data.get("time_to_first_node_ms", self.ttfn_ms)}
            self.latency_ms = data["latency_ms"]
        self.events.append({"type": kind, "data": data})
        self._notify()

    def finish(self, status: str) -> None:
        self.status = status
        if self.latency_ms is None:
            self.latency_ms = int((time.monotonic() - self.t0) * 1000)
        self._notify()

    async def wait_change(self, signal: asyncio.Event, timeout: float) -> None:
        try:
            await asyncio.wait_for(signal.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    def done_event(self) -> dict[str, Any]:
        return next((e["data"] for e in reversed(self.events) if e["type"] == "done"), {})

    def nodes(self) -> list[dict[str, Any]]:
        return [e["data"] for e in self.events if e["type"] == "node"]

    def summary(self) -> dict[str, Any]:
        """Completion callback body (contract): existing fields + engine + latency_ms."""
        done = self.done_event()
        best = done.get("best") or {}
        return {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "bug_id": self.bug_id,
            "mode": self.mode,
            "engine": self.engine,
            "solved": bool(done.get("solved", False)),
            "best_node_id": best.get("id"),
            "nodes": self.nodes(),
            "usage": done.get("usage", new_usage()),
            "latency_ms": done.get("latency_ms", self.latency_ms),
        }

    def public(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "bug_id": self.bug_id, "mode": self.mode, "engine": self.engine,
            "status": self.status, "events": self.events, "pr_draft": self.pr_draft, "pr_url": self.pr_url,
            "replay_of": self.replay_of,
        }

    def to_record(self) -> dict[str, Any]:
        return {
            **self.summary(), "status": self.status, "created_at": self.created_at,
            "replay_of": self.replay_of, "events": self.events, "pr_draft": self.pr_draft,
            "pr_url": self.pr_url, "trace_id": self.trace_id,
        }

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> Run:
        return cls(
            run_id=rec["run_id"], bug_id=rec["bug_id"], mode=rec["mode"], engine=rec.get("engine", "loop"),
            user_id=rec.get("user_id"), replay_of=rec.get("replay_of"), status=rec.get("status", "done"),
            created_at=rec.get("created_at", 0.0), events=rec.get("events", []),
            pr_draft=rec.get("pr_draft"), pr_url=rec.get("pr_url"), trace_id=rec.get("trace_id", ""),
            latency_ms=rec.get("latency_ms"),
        )


class RunRegistry:
    def __init__(self, settings: Settings, guard: GuardService | None = None) -> None:
        self.settings = settings
        self.guard = guard or GuardService(settings)
        self.runs: dict[str, Run] = {}
        self.live_runs_started = 0
        self._nebius: NebiusSandbox | None = None
        self._local = LocalSandbox(LOCAL_TEST_TIMEOUT, settings.sandbox_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    # ---- mode and wiring -------------------------------------------------

    def resolve_mode(self) -> str:
        """Configured mode, downgraded to fake when credentials are missing or the live budget is spent."""
        mode = self.settings.mode
        if mode == "fake" or not self.settings.llm_ready:
            return "fake"
        if mode == "live" and not self.settings.sandbox_ready:
            mode = "hybrid"
        self.live_runs_started += 1
        if self.live_runs_started > self.settings.max_live_runs:
            return "fake"
        return mode

    def nebius(self) -> NebiusSandbox:
        if self._nebius is None:
            self._nebius = NebiusSandbox(SANDBOX_TEST_TIMEOUT, concurrency=self.settings.sandbox_concurrency)
        return self._nebius

    def _sandbox(self, mode: str) -> Sandbox:
        return self.nebius() if mode == "live" else self._local

    def _search_config(self, run: Run) -> tuple[Any, SearchConfig]:
        usage = new_usage()
        timeout = SANDBOX_TEST_TIMEOUT if run.mode == "live" else LOCAL_TEST_TIMEOUT
        if run.mode == "fake":
            return propose_fake, SearchConfig(test_timeout=timeout, usage=usage)
        propose = functools.partial(
            propose_live, settings=self.settings,
            client=make_client(self.settings.nebius_api_key), usage=usage,
        )
        cfg = SearchConfig(
            test_timeout=timeout, usage=usage, model_override=run.model_override,
            model_for=lambda depth: model_for(depth, self.settings, run.model_override),
        )
        return propose, cfg

    def team(self, mode: str, model_override: str | None = None) -> Any:
        if mode == "fake":
            return FakeTeam(self.settings.fake_delay_scale)
        return LiveTeam(self.settings, model_override)

    # ---- lifecycle -------------------------------------------------------

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id) or self.load(run_id)

    def start(
        self, bug: Bug, user_id: str | None = None, model_override: str | None = None, mode: str | None = None,
        engine: str | None = None, trace_id: str = "", trace_headers: dict[str, str] | None = None,
    ) -> Run:
        """Start a run in the background. `mode` forces a mode (used for the fake replay fallback)."""
        run = Run(
            run_id=uuid.uuid4().hex, bug_id=bug["id"], mode=mode or self.resolve_mode(),
            engine=engine or self.settings.engine, user_id=user_id, model_override=model_override,
            trace_id=trace_id, trace_headers=dict(trace_headers or {}),
        )
        self.runs[run.run_id] = run
        run.emit("run_started", {"run_id": run.run_id, "bug_id": run.bug_id, "mode": run.mode, "engine": run.engine})
        self._spawn(self._execute(run, bug))
        return run

    def start_replay(self, source: Run, user_id: str | None = None, trace_id: str = "") -> Run:
        run = Run(
            run_id=uuid.uuid4().hex, bug_id=source.bug_id, mode="replay", engine=source.engine,
            user_id=user_id, replay_of=source.run_id, trace_id=trace_id, pr_draft=source.pr_draft,
        )
        self.runs[run.run_id] = run
        run.emit("run_started", {"run_id": run.run_id, "bug_id": run.bug_id, "mode": "replay",
                                 "engine": run.engine, "replay_of": source.run_id})
        self._spawn(self._replay(run, source))
        return run

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute(self, run: Run, bug: Bug) -> None:
        run_id_var.set(run.run_id)
        trace_id_var.set(run.trace_id)

        async def emit(kind: str, data: dict[str, Any]) -> None:
            run.emit(kind, data)

        status = "done"
        ctx: GraphCtx | None = None
        with background_run(f"run/{run.engine}", run.trace_headers):
            try:
                sandbox = self._sandbox(run.mode)
                timeout = SANDBOX_TEST_TIMEOUT if run.mode == "live" else LOCAL_TEST_TIMEOUT
                if run.engine == "graph":
                    ctx = GraphCtx(
                        run_id=run.run_id, bug=bug, mode=run.mode, settings=self.settings, sandbox=sandbox,
                        team=self.team(run.mode, run.model_override), guard=self.guard, emit=emit,
                        test_timeout=timeout,
                    )
                    await run_graph(ctx)
                    run.pr_draft = ctx.pr_draft
                else:
                    event = await self.guard.check("input", f"{bug['issue']}\n\n{bug['buggy']}", run.mode, run.run_id)
                    run.emit("guard", event)
                    if event["verdict"] == "block":
                        run.emit("error", {"stage": "input_guard",
                                           "message": "input blocked by guardrails: " + "; ".join(event["reasons"])})
                    else:
                        propose, cfg = self._search_config(run)
                        await run_search(bug, sandbox, propose, emit, cfg)
                if any(e["type"] == "error" and e["data"].get("stage") == "input_guard" for e in run.events):
                    status = "blocked"
            except BudgetExceeded:
                status = "budget"
            except Exception as exc:
                log.exception("run %s failed", run.run_id)
                run.emit("error", {"stage": "engine", "message": f"{type(exc).__name__}: {exc}"})
                status = "error"
            run.finish(status)
            self._record_metrics(run, ctx)
        self.save(run)
        await self._report(run)

    def _record_metrics(self, run: Run, ctx: GraphCtx | None) -> None:
        done = run.done_event()
        usage = done.get("usage") or {}
        record_event("PatchLoopRun", {
            "run_id": run.run_id, "bug_id": run.bug_id, "engine": run.engine, "mode": run.mode,
            "solved": bool(done.get("solved")), "status": run.status,
            "rounds": sum(1 for e in run.events if e["type"] == "round"),
            "candidates": max(0, len(run.nodes()) - 1),
            "tokens": int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0)),
            "latency_ms": run.latency_ms or 0, "ttfn_ms": run.ttfn_ms or 0,
            "cancelled": ctx.cancelled if ctx else 0,
        })
        log.info("run finished status=%s solved=%s latency_ms=%s ttfn_ms=%s",
                 run.status, bool(done.get("solved")), run.latency_ms, run.ttfn_ms)

    async def _replay(self, run: Run, source: Run) -> None:
        for event in source.events:
            if event["type"] in REPLAYED_TYPES:
                await asyncio.sleep(REPLAY_PACING)
                data = dict(event["data"])
                if event["type"] == "done":  # report the replay's own timings
                    data.pop("latency_ms", None)
                    data.pop("time_to_first_node_ms", None)
                run.emit(event["type"], data)
        run.finish("done")
        await self._report(run)

    async def _report(self, run: Run) -> None:
        await post_completion(self.settings.backend_callback_url, self.settings.shared_secret, run.summary(),
                              trace_id=run.trace_id)

    # ---- persistence -----------------------------------------------------

    def _path(self, run_id: str) -> Path:
        return self.settings.runs_dir / f"{run_id}.json"

    def save(self, run: Run) -> None:
        try:
            self.settings.runs_dir.mkdir(parents=True, exist_ok=True)
            self._path(run.run_id).write_text(json.dumps(run.to_record(), indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("could not persist run %s: %s", run.run_id, exc)

    def load(self, run_id: str) -> Run | None:
        if not run_id.isalnum():
            return None
        path = self._path(run_id)
        if not path.is_file():
            return None
        try:
            return Run.from_record(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            return None

    def saved_replays(self, bug_id: str | None = None) -> list[dict[str, Any]]:
        """Solved real (non-fake) runs on disk, best first."""
        found = []
        for path in self.settings.runs_dir.glob("*.json"):
            run = self.load(path.stem)
            if run is None or run.mode not in REAL_MODES or (bug_id and run.bug_id != bug_id):
                continue
            done = run.done_event()
            if not done.get("solved"):
                continue
            best = done.get("best") or {}
            found.append({
                "run_id": run.run_id, "bug_id": run.bug_id, "mode": run.mode, "engine": run.engine,
                "best_score": best.get("score", 0.0), "nodes": len(run.nodes()),
                "created_at": run.created_at,
            })
        return sorted(found, key=lambda r: (r["best_score"], r["created_at"]), reverse=True)

    def best_replay(self, bug_id: str) -> Run | None:
        saved = self.saved_replays(bug_id)
        return self.load(saved[0]["run_id"]) if saved else None
