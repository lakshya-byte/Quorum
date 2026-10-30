"""Run budgets. The env sets CAPS; user/planner requests are clamped, never trusted (contract section 2)."""
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from app.swarm.types import Emit


@dataclass(frozen=True)
class Limits:
    max_workers: int
    max_tokens: int
    max_wall_s: float
    worker_max_steps: int
    max_rounds: int
    max_units: int

    def public(self) -> dict[str, Any]:
        return {"max_workers": self.max_workers, "max_tokens": self.max_tokens, "max_wall_s": self.max_wall_s,
                "worker_max_steps": self.worker_max_steps, "max_rounds": self.max_rounds}


def _clamp(requested: Any, cap: float, floor: float = 1) -> float:
    try:
        value = float(requested)
    except (TypeError, ValueError):
        return cap
    if value != value:  # NaN
        return cap
    return max(floor, min(value, cap))


def resolve_limits(settings: Any, requested: dict[str, Any] | None = None) -> Limits:
    """Env caps (Settings.swarm_*) clamp the request. A missing/invalid request value means 'use the cap'."""
    req = requested or {}
    cap_w, cap_t, cap_s = settings.swarm_max_workers, settings.swarm_max_tokens, settings.swarm_max_wall_s
    return Limits(
        max_workers=int(_clamp(req.get("max_workers", cap_w), cap_w)),
        max_tokens=int(_clamp(req.get("max_tokens", cap_t), cap_t, 1000)),
        max_wall_s=float(_clamp(req.get("max_wall_s", cap_s), cap_s, 1)),
        worker_max_steps=int(settings.swarm_worker_max_steps),
        max_rounds=int(settings.swarm_max_rounds),
        max_units=int(settings.swarm_max_units),
    )


@dataclass
class Budget:
    limits: Limits
    started: float = field(default_factory=time.monotonic)
    tokens_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    workers_active: int = 0
    peak_parallel: int = 0
    sem: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.sem = asyncio.Semaphore(self.limits.max_workers)

    @property
    def wall_s(self) -> float:
        return time.monotonic() - self.started

    def add_usage(self, usage: dict[str, int] | None) -> None:
        if not usage:
            return
        p, c = int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
        self.prompt_tokens += p
        self.completion_tokens += c
        self.tokens_used += p + c
        self.calls += 1

    def exhausted(self) -> str:
        """'' while there is budget; otherwise the reason."""
        if self.tokens_used >= self.limits.max_tokens:
            return f"token budget exhausted ({self.tokens_used}/{self.limits.max_tokens})"
        if self.wall_s >= self.limits.max_wall_s:
            return f"wall-time budget exhausted ({int(self.wall_s)}s/{int(self.limits.max_wall_s)}s)"
        return ""

    def remaining_wall(self) -> float:
        return max(0.0, self.limits.max_wall_s - self.wall_s)

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """One worker slot: concurrency never exceeds limits.max_workers."""
        await self.sem.acquire()
        self.workers_active += 1
        self.peak_parallel = max(self.peak_parallel, self.workers_active)
        try:
            yield
        finally:
            self.workers_active -= 1
            self.sem.release()

    def snapshot(self) -> dict[str, Any]:
        return {"tokens_used": self.tokens_used, "tokens_limit": self.limits.max_tokens,
                "wall_s": round(self.wall_s, 1), "wall_limit_s": self.limits.max_wall_s,
                "workers_active": self.workers_active}

    def usage(self) -> dict[str, int]:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}


async def budget_ticker(budget: Budget, emit: Emit, interval: float = 1.5) -> None:
    """`budget` event every <= 2 s while the run is alive (cancelled by the engine at the end)."""
    interval = min(interval, 2.0)
    while True:
        await emit("budget", budget.snapshot())
        await asyncio.sleep(interval)
