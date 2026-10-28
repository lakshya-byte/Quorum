"""In-memory run registry: starts searches, logs events, persists finished runs, replays saved ones."""
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

from app.bugs import Bug
from app.callbacks import post_completion
from app.config import LOCAL_TEST_TIMEOUT, SANDBOX_TEST_TIMEOUT, Settings
from app.llm import make_client
from app.proposers import model_for, new_usage, propose_fake, propose_live
from app.sandbox import LocalSandbox, NebiusSandbox, Sandbox
from app.search import SearchConfig, run_search

log = logging.getLogger(__name__)

REPLAY_PACING = 0.3
REAL_MODES = ("hybrid", "live")


@dataclass
class Run:
    run_id: str
    bug_id: str
    mode: str
    user_id: str | None = None
    model_override: str | None = None
    replay_of: str | None = None
    status: str = "running"  # running | done | error
    created_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.status != "running"

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        self.events.append({"type": kind, "data": data})

    def done_event(self) -> dict[str, Any]:
        return next((e["data"] for e in reversed(self.events) if e["type"] == "done"), {})

    def nodes(self) -> list[dict[str, Any]]:
        return [e["data"] for e in self.events if e["type"] == "node"]

    def summary(self) -> dict[str, Any]:
        done = self.done_event()
        best = done.get("best") or {}
        return {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "bug_id": self.bug_id,
            "mode": self.mode,
            "solved": bool(done.get("solved", False)),
            "best_node_id": best.get("id"),
            "nodes": self.nodes(),
            "usage": done.get("usage", new_usage()),
        }

    def public(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "bug_id": self.bug_id, "mode": self.mode,
            "status": self.status, "events": self.events,
        }

    def to_record(self) -> dict[str, Any]:
        return {
            **self.summary(), "status": self.status, "created_at": self.created_at,
            "replay_of": self.replay_of, "events": self.events,
        }

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> Run:
        return cls(
            run_id=rec["run_id"], bug_id=rec["bug_id"], mode=rec["mode"], user_id=rec.get("user_id"),
            replay_of=rec.get("replay_of"), status=rec.get("status", "done"),
            created_at=rec.get("created_at", 0.0), events=rec.get("events", []),
        )


class RunRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runs: dict[str, Run] = {}
        self.live_runs_started = 0
        self._nebius: NebiusSandbox | None = None
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

    def _sandbox(self, mode: str) -> Sandbox:
        if mode != "live":
            return LocalSandbox(LOCAL_TEST_TIMEOUT)
        if self._nebius is None:
            self._nebius = NebiusSandbox(SANDBOX_TEST_TIMEOUT)
        return self._nebius

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

    # ---- lifecycle -------------------------------------------------------

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id) or self.load(run_id)

    def start(self, bug: Bug, user_id: str | None = None, model_override: str | None = None) -> Run:
        run = Run(
            run_id=uuid.uuid4().hex, bug_id=bug["id"], mode=self.resolve_mode(),
            user_id=user_id, model_override=model_override,
        )
        self.runs[run.run_id] = run
        self._spawn(self._execute(run, bug))
        return run

    def start_replay(self, source: Run, user_id: str | None = None) -> Run:
        run = Run(
            run_id=uuid.uuid4().hex, bug_id=source.bug_id, mode="replay",
            user_id=user_id, replay_of=source.run_id,
        )
        self.runs[run.run_id] = run
        self._spawn(self._replay(run, source))
        return run

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute(self, run: Run, bug: Bug) -> None:
        async def emit(kind: str, data: dict[str, Any]) -> None:
            run.emit(kind, data)

        try:
            propose, cfg = self._search_config(run)
            await run_search(bug, self._sandbox(run.mode), propose, emit, cfg)
            run.status = "done"
        except Exception as exc:
            log.exception("run %s failed", run.run_id)
            run.emit("error", {"message": f"{type(exc).__name__}: {exc}"})
            run.status = "error"
        self.save(run)
        await self._report(run)

    async def _replay(self, run: Run, source: Run) -> None:
        for event in source.events:
            if event["type"] in ("node", "round", "done", "error"):
                await asyncio.sleep(REPLAY_PACING)
                run.emit(event["type"], event["data"])
        run.status = "done"
        await self._report(run)

    async def _report(self, run: Run) -> None:
        await post_completion(self.settings.backend_callback_url, self.settings.shared_secret, run.summary())

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
                "run_id": run.run_id, "bug_id": run.bug_id, "mode": run.mode,
                "best_score": best.get("score", 0.0), "nodes": len(run.nodes()),
                "created_at": run.created_at,
            })
        return sorted(found, key=lambda r: (r["best_score"], r["created_at"]), reverse=True)

    def best_replay(self, bug_id: str) -> Run | None:
        saved = self.saved_replays(bug_id)
        return self.load(saved[0]["run_id"]) if saved else None
