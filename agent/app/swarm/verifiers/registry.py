"""Verifier registry and the per-call context object."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.swarm.artifacts import ArtifactStore
from app.swarm.repo_map import RepoMap, build_repo_map
from app.swarm.verifiers.common import current_files, state_hash
from app.swarm.verifiers.types import Baseline, Criterion, VerifyResult

Verifier = Callable[[Criterion, "Ctx"], Awaitable[VerifyResult]]
VERIFIERS: dict[str, Verifier] = {}


def register(*kinds: str) -> Callable[[Verifier], Verifier]:
    def deco(fn: Verifier) -> Verifier:
        for k in kinds:
            VERIFIERS[k] = fn
        return fn
    return deco


@dataclass
class Ctx:
    ws: Any
    baseline: Baseline
    store: ArtifactStore
    judge: Callable[..., Awaitable[dict]] | None = None
    _files: dict[str, str] | None = field(default=None, repr=False)
    _rm: RepoMap | None = field(default=None, repr=False)

    async def files(self, refresh: bool = False) -> dict[str, str]:
        if self._files is None or refresh:
            self._files = await current_files(self.ws, self.baseline)
            self._rm = None
        return self._files

    async def repo_map(self) -> RepoMap:
        files = await self.files()
        if self._rm is None:
            self._rm = build_repo_map(files)
        return self._rm

    async def state(self) -> str:
        return state_hash(await self.files())


def result(c: Criterion, status: str, detail: str, *, score: float | None = None, artifacts=None, **meta) -> VerifyResult:
    return VerifyResult(c.id, c.kind, c.hard, status, score, detail, list(artifacts or []), dict(meta))


def skip(c: Criterion, reason: str) -> VerifyResult:
    return result(c, "skip", reason)
