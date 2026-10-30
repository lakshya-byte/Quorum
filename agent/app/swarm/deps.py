"""Adapter seam to builder B's modules (workspace, verifiers, repo_map, artifacts). Imported lazily so the swarm core
(and its tests, which inject fakes) never needs them at import time, and a missing module gives a readable error.

What B's code must provide (contract section 6, plus the small conventions this adapter relies on):

  app/swarm/workspace.py    get_factory(mode: str, *, allow_local: bool = False, settings=None) -> WorkspaceFactory
                            (fallbacks tried: make_factory(...), then LocalWorkspaceFactory()/NebiusWorkspaceFactory(settings))
                            Workspace: isolation, list_dir, read, write, search, exec, changed, fork, release
                            optional: `delete(path)` (without it, file deletions are reported and not applied)
                            ExecResult: a (code, stdout_tail, duration_ms) tuple or an object with .code/.stdout_tail/.duration_ms
  app/swarm/verifiers/      Criterion(id, kind, hard, description, params), run_verifier(c, ws, baseline, artifacts),
                            collect_baseline(ws, repo_map), build_repo_map(files), ArtifactStore (add/list/get)
                            (build_repo_map / ArtifactStore may instead live in app/swarm/repo_map.py / artifacts.py)
"""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Any


class SwarmDepsError(RuntimeError):
    """A swarm dependency (sandbox workspace or verifier registry) is not available. The message is user-presentable."""


@dataclass
class SwarmDeps:
    workspace_factory: Any  # WorkspaceFactory
    run_verifier: Any  # async (Criterion, ws, baseline, artifacts) -> VerifyResult
    collect_baseline: Any  # async (ws, repo_map) -> Baseline
    build_repo_map: Any  # (files) -> RepoMap
    criterion_cls: Any  # Criterion dataclass
    artifact_store_cls: Any  # ArtifactStore class

    def new_store(self) -> Any:
        return self.artifact_store_cls()

    async def baseline(self, ws: Any, repo_map: Any, store: Any) -> Any:
        """collect_baseline(ws, repo_map[, artifacts]): the artifact store is passed when the function accepts it
        (before-screenshots then land in the run's gallery)."""
        try:
            accepts = "artifacts" in inspect.signature(self.collect_baseline).parameters
        except (TypeError, ValueError):
            accepts = False
        if accepts:
            return await self.collect_baseline(ws, repo_map, artifacts=store)
        return await self.collect_baseline(ws, repo_map)

    def criterion(self, spec: Any) -> Any:
        return self.criterion_cls(id=spec.id, kind=spec.verifier or spec.kind, hard=bool(spec.hard),
                                  description=spec.description, params=dict(spec.params))


def _import(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise SwarmDepsError(f"swarm dependency {name!r} is not available ({exc}). The sandbox workspace and verifier "
                             f"modules are required for non-bugfix tasks.") from None


def _construct(cls: Any, **candidates: Any) -> Any:
    """Instantiate `cls` passing only the keyword arguments its __init__ declares."""
    try:
        params = inspect.signature(cls).parameters
    except (TypeError, ValueError):
        return cls()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return cls(**candidates)
    return cls(**{k: v for k, v in candidates.items() if k in params})


def _first(obj: Any, *names: str) -> Any:
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


def load_deps(mode: str, settings: Any, *, demo: bool) -> SwarmDeps:
    ws_mod = _import("app.swarm.workspace")
    ver = _import("app.swarm.verifiers")
    allow_local = bool(demo or getattr(settings, "allow_local_repo_exec", False))
    maker = _first(ws_mod, "get_factory", "make_factory")
    if maker is not None:
        factory = maker(mode, allow_local=allow_local, settings=settings)
    else:
        cls = _first(ws_mod, "NebiusWorkspaceFactory" if mode == "live" else "LocalWorkspaceFactory",
                     "LocalWorkspaceFactory")
        if cls is None:
            raise SwarmDepsError("app.swarm.workspace has no get_factory()/make_factory()/WorkspaceFactory class")
        factory = _construct(cls, settings=settings, demo=demo or None, allow_non_demo=allow_local,
                             concurrency=int(getattr(settings, "sandbox_concurrency", 8)))
    repo_map = _first(ver, "build_repo_map")
    store = _first(ver, "ArtifactStore")
    if repo_map is None:
        repo_map = _first(_import("app.swarm.repo_map"), "build_repo_map")
    if store is None:
        store = _first(_import("app.swarm.artifacts"), "ArtifactStore")
    needed = {"run_verifier": _first(ver, "run_verifier"), "collect_baseline": _first(ver, "collect_baseline"),
              "Criterion": _first(ver, "Criterion"), "build_repo_map": repo_map, "ArtifactStore": store}
    missing = [k for k, v in needed.items() if v is None]
    if missing:
        raise SwarmDepsError(f"verifier modules are missing: {', '.join(missing)}")
    return SwarmDeps(factory, needed["run_verifier"], needed["collect_baseline"], repo_map, needed["Criterion"], store)
