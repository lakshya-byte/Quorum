"""Data types of the swarm (contract v3 section 4): plan, units, criteria, worker results, run context.

Everything the LLM produces is parsed into these pydantic models and then SANITISED IN CODE (planner.finalize_plan):
the model proposes, plain code disposes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TASK_TYPES = ("bugfix", "feature", "refactor", "ui", "tests", "perf", "deps", "docs", "migration", "other")
REQUESTED_TYPES = ("auto",) + TASK_TYPES
CRITERION_KINDS = (
    "build", "tests", "no_regression", "policy", "security", "secrets", "repro", "acceptance_tests",
    "characterization", "api_surface", "lint_typecheck", "complexity_metric", "ui_build_console", "ui_overflow",
    "ui_axe", "ui_smoke", "command", "benchmark", "advisory_vision", "advisory_rubric",
)
ADVISORY_KINDS = ("advisory_vision", "advisory_rubric")
# Criteria whose verifier is a test/script the swarm itself writes (and must validate before relying on it).
SYNTHESIZED_KINDS = ("acceptance_tests", "characterization", "ui_smoke", "repro")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,59}$")

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


def slug(text: str, fallback: str = "x") -> str:
    out = re.sub(r"[^a-z0-9_.-]+", "-", (text or "").lower()).strip("-.")[:50]
    return out if out and SAFE_ID.match(out) else fallback


class Question(BaseModel):
    id: str
    text: str = Field(min_length=1, max_length=400)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return slug(str(v), "q")


class CriterionSpec(BaseModel):
    """One success criterion. `verifier` names the executable check (defaults to `kind`)."""

    id: str
    kind: str
    hard: bool = True
    description: str = Field(default="", max_length=400)
    verifier: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    user_stated: bool = False  # the user's own words asked for it (a downgrade then makes the outcome `partial`)
    downgraded: str = ""  # why a hard criterion became advisory (never silent)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return slug(str(v), "criterion")

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        v = str(v).strip().lower()
        if v not in CRITERION_KINDS:
            raise ValueError(f"unknown criterion kind {v!r}; allowed: {', '.join(CRITERION_KINDS)}")
        return v

    @model_validator(mode="after")
    def _defaults(self) -> "CriterionSpec":
        self.verifier = self.verifier or self.kind
        if self.kind in ADVISORY_KINDS:
            self.hard = False  # vision/rubric opinions never gate (unless the task promotes them with `strict`)
        return self


class Unit(BaseModel):
    id: str
    title: str = Field(default="", max_length=160)
    scope_files: list[str] = Field(default_factory=list)  # exact paths, dir prefixes ending in "/", or globs
    depends_on: list[str] = Field(default_factory=list)
    variants: int = Field(default=1, ge=1, le=8)
    role: str = "worker"
    instructions: str = Field(default="", max_length=3000)
    checks: list[str] = Field(default_factory=list)  # unit-level commands (allow-listed), e.g. affected tests
    risk: Literal["low", "medium", "high"] = "low"

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return slug(str(v), "unit")


class SwarmSizing(BaseModel):
    max_parallel: int = 1
    workers_planned: int = 1
    limits: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    task_type: str = "other"
    task_type_source: Literal["auto", "user"] = "auto"
    strategy: Literal["swarm", "bugfix"] = "swarm"  # bugfix = the existing graph engine (cheap path)
    cheap_path: bool = False  # the planner's opinion: a small single-cause bug with a reproducible failure
    summary: str = Field(default="", max_length=800)
    criteria: list[CriterionSpec] = Field(default_factory=list)
    units: list[Unit] = Field(default_factory=list)
    swarm: SwarmSizing = Field(default_factory=SwarmSizing)
    clarify: list[Question] = Field(default_factory=list)  # non-empty => needs_input
    notes: list[str] = Field(default_factory=list)  # honest remarks (downgrades, clamps, dropped files)

    @field_validator("task_type")
    @classmethod
    def _type(cls, v: str) -> str:
        v = str(v).strip().lower()
        return v if v in TASK_TYPES else "other"

    @model_validator(mode="after")
    def _graph(self) -> "Plan":
        ids = [u.id for u in self.units]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate unit ids")
        for u in self.units:
            missing = [d for d in u.depends_on if d not in ids]
            if missing:
                raise ValueError(f"unit {u.id} depends on unknown units {missing}")
        if cycle(self.units):
            raise ValueError("unit dependencies contain a cycle")
        cids = [c.id for c in self.criteria]
        if len(set(cids)) != len(cids):
            raise ValueError("duplicate criterion ids")
        return self


def cycle(units: list[Unit]) -> bool:
    deps = {u.id: set(u.depends_on) for u in units}
    done: set[str] = set()
    while deps:
        ready = [k for k, v in deps.items() if v <= done]
        if not ready:
            return True
        for k in ready:
            done.add(k)
            del deps[k]
    return False


def topo_order(units: list[Unit]) -> list[Unit]:
    by_id = {u.id: u for u in units}
    out: list[Unit] = []
    seen: set[str] = set()

    def visit(uid: str) -> None:
        if uid in seen:
            return
        seen.add(uid)
        for d in by_id[uid].depends_on:
            visit(d)
        out.append(by_id[uid])

    for u in units:
        visit(u.id)
    return out


@dataclass
class WorkerResult:
    unit_id: str
    variant: int
    ok: bool
    summary: str = ""
    changes: dict[str, str | None] = field(default_factory=dict)  # path -> new text (None = deleted)
    start_texts: dict[str, str | None] = field(default_factory=dict)  # path -> text when the unit started
    diff: str = ""
    tokens: int = 0
    steps: int = 0
    failure: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    model: str = ""


@dataclass
class UnitState:
    unit: Unit
    status: str = "pending"  # pending|running|passed|failed|cancelled|merged
    result: WorkerResult | None = None
    attempts: int = 0
    failures: list[str] = field(default_factory=list)


@dataclass
class VerifyRow:
    """One verifier result as the swarm uses it (events + outcome)."""

    criterion_id: str
    kind: str
    hard: bool
    status: str  # pass | fail | skip | advisory
    score: float | None = None
    detail: str = ""
    artifacts: list[str] = field(default_factory=list)

    def event(self) -> dict[str, Any]:
        out: dict[str, Any] = {"criterion_id": self.criterion_id, "kind": self.kind, "hard": self.hard,
                               "status": self.status, "detail": self.detail[:500], "artifacts": list(self.artifacts)}
        if self.score is not None:
            out["score"] = self.score
        return out


@dataclass
class SwarmCtx:
    """Everything one swarm run needs. `deps`, `llm_factory` and `emit` are injectable so tests run offline."""

    run_id: str
    task: str
    full_name: str
    files: dict[str, str]
    settings: Any
    emit: Emit
    deps: Any  # SwarmDeps (swarm/deps.py)
    llm_factory: Callable[[str, str], Any]  # (role, tier "nano"|"super") -> ChatLLM
    mode: str = "fake"
    task_type: str = "auto"
    strict: list[str] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)
    answers: dict[str, str] = field(default_factory=dict)
    language: str = "unknown"
    demo: bool = False
    secrets: list[str] = field(default_factory=list)  # strings to scrub from every event (e.g. the GitHub token)
    guard_event: dict[str, Any] | None = None
    fake: Any = None  # FakeSwarm when scripted
    trace_tags: list[str] = field(default_factory=list)
    trace_meta: dict[str, Any] = field(default_factory=dict)
    plan: Plan | None = None  # precomputed (the repo flow plans first to choose the strategy)
    plan_usage: dict[str, int] = field(default_factory=dict)
    budget_tick_s: float = 1.5
    # filled in by the engine, read by the repo flow
    result: dict[str, Any] = field(default_factory=dict)
