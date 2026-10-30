"""Dataclasses shared by every verifier (contract v3 section 6)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.swarm.artifacts import Artifact

STATUSES = ("pass", "fail", "skip", "advisory")


@dataclass
class Criterion:
    id: str
    kind: str
    hard: bool
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerifyResult:
    criterion_id: str
    kind: str
    hard: bool
    status: str  # pass | fail | skip | advisory
    score: float | None = None
    detail: str = ""
    artifacts: list[Artifact] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)  # machine-readable extras (counts, ids); not for prompts

    def event(self) -> dict[str, Any]:
        """The `verify.results[]` item of the SSE contract (detail clipped to 500 chars)."""
        return {"criterion_id": self.criterion_id, "kind": self.kind, "hard": self.hard, "status": self.status,
                "score": self.score, "detail": self.detail[:500], "artifacts": [a.id for a in self.artifacts]}


@dataclass
class Baseline:
    """Facts about the ORIGINAL repo, collected once in the sandbox before any worker runs."""
    files: dict[str, str] = field(default_factory=dict)  # original text snapshot (verifiers diff against it)
    build: dict[str, Any] = field(default_factory=dict)  # {status, command, detail}
    tests: dict[str, Any] = field(default_factory=dict)  # {status, command, passing:set, failing:set, total, detail}
    lint: dict[str, Any] = field(default_factory=dict)  # {tool: {"count": n, "command": ...}}
    ui: dict[str, Any] = field(default_factory=dict)  # {status, reason, viewports, axe, console_errors, dist_files}
    repo_map: Any = None
    notes: list[str] = field(default_factory=list)

    @property
    def passing_tests(self) -> set[str]:
        return set(self.tests.get("passing", ()))

    def summary(self) -> dict[str, Any]:
        ui = self.ui
        return {
            "build": self.build.get("status"), "tests_total": self.tests.get("total"),
            "tests_passing": len(self.passing_tests), "tests_status": self.tests.get("status"),
            "lint": {k: v.get("count") for k, v in self.lint.items()},
            "ui": {"status": ui.get("status"), "reason": ui.get("reason"),
                   "axe_rules": (ui.get("axe") or {}).get("rules"), "axe_nodes": (ui.get("axe") or {}).get("nodes"),
                   "overflow": {k: v.get("overflow") for k, v in (ui.get("viewports") or {}).items()}},
            "notes": self.notes,
        }
