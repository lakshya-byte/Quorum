"""Loader for the swarm demo repos (`agent/app/demo_repos/<name>/swarm_tasks.json`).

Layout per repo: `repo/` (original files), `reference/<task>/` (hidden reference solution as full file contents),
`bad/<name>/` (deliberately wrong solutions used to prove the gates), `acceptance/` (spec tests the planner's spec
agent would write), `smoke/` (UI key-flow scripts). Fake-mode scripted workers replay `Solution.files` against the
REAL workspace and verifiers; nothing here is read by the live LLM path.

These repos are intentionally NOT registered with `repo_loader.demo_names()` (they carry no meta.json), so the v1
demo listing and its tests are untouched; integrate through `load_swarm_demo` / `swarm_demo_names`."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.repo_loader import DEMO_DIR, _read_tree
from app.swarm.verifiers.types import Criterion


@dataclass
class Solution:
    files: dict[str, str]
    delete: list[str] = field(default_factory=list)
    units: list[dict[str, Any]] = field(default_factory=list)  # optional split into units (path groups)
    note: str = ""

    async def apply(self, ws: Any) -> None:
        for path, text in self.files.items():
            await ws.write(path, text)
        for path in self.delete:
            await ws.delete(path)


@dataclass
class DemoTask:
    id: str
    task_type: str
    title: str
    prompt: str
    criteria: list[Criterion]
    reference: Solution
    bad: dict[str, Solution]
    repo: str = ""


@dataclass
class SwarmDemo:
    name: str
    files: dict[str, str]
    tasks: dict[str, DemoTask]
    language_hint: str = ""
    description: str = ""

    def task(self, task_id: str) -> DemoTask:
        return self.tasks[task_id]


def swarm_demo_names() -> list[str]:
    return sorted(p.name for p in DEMO_DIR.iterdir() if (p / "swarm_tasks.json").is_file()) if DEMO_DIR.is_dir() else []


def _solution(base: Path, spec: dict[str, Any]) -> Solution:
    return Solution(_read_tree(base / spec["dir"]), list(spec.get("delete", [])), list(spec.get("units", [])),
                    spec.get("note", ""))


def load_swarm_demo(name: str) -> SwarmDemo:
    if name not in swarm_demo_names():
        raise KeyError(f"unknown swarm demo repo {name!r}; available: {', '.join(swarm_demo_names())}")
    base = DEMO_DIR / name
    spec = json.loads((base / "swarm_tasks.json").read_text(encoding="utf-8"))
    tasks: dict[str, DemoTask] = {}
    for t in spec["tasks"]:
        criteria = []
        for c in t["criteria"]:
            params = dict(c.get("params") or {})
            if "files_from" in params:
                params["files"] = {dest: (base / src).read_text(encoding="utf-8") for dest, src in params.pop("files_from").items()}
            if "script_from" in params:
                params["script"] = (base / params.pop("script_from")).read_text(encoding="utf-8")
            criteria.append(Criterion(c["id"], c["kind"], bool(c["hard"]), c.get("description", ""), params))
        tasks[t["id"]] = DemoTask(
            t["id"], t["task_type"], t["title"], t["prompt"], criteria, _solution(base, t["reference"]),
            {k: _solution(base, v) for k, v in (t.get("bad") or {}).items()}, name)
    return SwarmDemo(name, _read_tree(base / "repo"), tasks, spec.get("language_hint", ""), spec.get("description", ""))
