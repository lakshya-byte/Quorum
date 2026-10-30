"""Golden dataset: pydantic models, loader, validator and JSON Schema export.

The file on disk is `evals/golden/golden_dataset.json`; `evals/golden/golden.schema.json` is generated from the
same models (`python -m evals.build_golden --schema`). Structural validation lives here; the executable
integrity proof (reference fix passes, original fails, ...) lives in `evals/integrity.py`.
"""
from __future__ import annotations

import fnmatch
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evals.common import GOLDEN_PATH, SCHEMA_PATH, sha256_text

SCHEMA_VERSION = "1.0"

Category = Literal["bug_fix_single_file", "bug_fix_multi_file", "locator_retrieval", "reproducer_quality",
                   "safety_guardrails", "unsolvable_or_underspecified", "followup_change_request", "pr_quality"]
Difficulty = Literal["easy", "medium", "hard"]
Source = Literal["web", "cli", "slack", "github"]
Stage = Literal["solved", "pr_opened", "blocked_guard", "stopped_locate", "stopped_no_signal", "stopped_no_tests",
                "unsolved_exhausted", "policy_blocked", "security_blocked", "probe_complete"]

CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]
CATEGORY_MINIMUMS: dict[str, int] = {
    "bug_fix_single_file": 9, "bug_fix_multi_file": 3, "locator_retrieval": 3, "reproducer_quality": 2,
    "safety_guardrails": 4, "unsolvable_or_underspecified": 2, "followup_change_request": 2, "pr_quality": 2,
}
MIN_TOTAL_CASES = 24
AGENT_TOOLS = ("input_guard", "locator", "test_writer", "triage", "proposer", "policy_gate", "sandbox_test",
               "security_scan", "critic", "reviewer", "output_guard")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FollowUp(Strict):
    message: str = Field(min_length=3, description="the reviewer's change request")
    pr_branch: str = Field(min_length=1)
    pr_number: int = Field(ge=1)
    previous_files: Literal["reference"] = Field(
        default="reference", description="the PR branch already contains the reference (correct) fix")


class CaseInput(Strict):
    task: str = Field(min_length=3, description="what a real user typed; vague where realistic")
    repo: str = Field(min_length=1, description="bundled bug id (e.g. 'paginate') or a demo repo ('demo/shop-api')")
    source: Source = "web"
    alert: str | None = Field(default=None, description="optional pasted alert / stack trace / error text")
    issue_ref: int | None = Field(default=None, ge=1, description="GitHub issue number the PR should close")
    followup: FollowUp | None = None
    adversarial_patch: dict[str, str] | None = Field(
        default=None, description="safety probes: files a hostile or careless candidate tries to write")

    @property
    def full_text(self) -> str:
        return self.task if not self.alert else f"{self.task}\n\n{self.alert}"


class PrRequirements(Strict):
    required_sections: list[str] = Field(default_factory=list)
    fixes_ref: bool = False


class Expected(Strict):
    solved: bool
    expected_stage: Stage
    also_acceptable_stages: list[Stage] = Field(
        default_factory=list, description="other honest stops a stronger agent may legitimately reach")
    locate_files: list[str] = Field(default_factory=list, description="ground-truth relevant source files")
    min_files_changed: int = Field(default=0, ge=0)
    max_files_changed: int = Field(default=0, ge=0)
    must_not_touch: list[str] = Field(default_factory=list, description="globs the fix may never change")
    repro_should_fail_on_original: bool | None = None
    guard_verdict: Literal["pass", "block"] = "pass"
    policy_expected: Literal["pass", "block", "n/a"] = "n/a"
    security_expected: Literal["pass", "block", "n/a"] = "n/a"
    expected_tools: list[str] = Field(default_factory=list)
    pr: PrRequirements | None = None
    followup_same_branch: bool | None = None

    @field_validator("expected_tools")
    @classmethod
    def known_tools(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in AGENT_TOOLS]
        if bad:
            raise ValueError(f"unknown tools {bad}; allowed: {list(AGENT_TOOLS)}")
        return v

    @model_validator(mode="after")
    def bounds(self) -> "Expected":
        if self.max_files_changed < self.min_files_changed:
            raise ValueError("max_files_changed < min_files_changed")
        return self


class Reference(Strict):
    root_cause: str = Field(min_length=10)
    fix_summary: str = Field(min_length=3)
    reference_files: list[str] = Field(default_factory=list)
    reference_diff: str = Field(default="", description="unified diff original -> bundled `correct` fix")
    reference_lines_changed: int = Field(default=0, ge=0)
    key_facts: list[str] = Field(default_factory=list, description="concept facts a good PR/explanation states")
    must_mention: list[str] = Field(default_factory=list,
                                    description="literals derived from the diff (paths, function names)")


class Metadata(Strict):
    derived_from: str = ""
    tier: str = ""
    fake_script: Literal["default", "no_reproducer", "no_locator_hint"] = "default"
    notes: str = ""
    author: str = "patchloop-evals"


class Case(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,60}$")
    category: Category
    difficulty: Difficulty
    title: str = Field(min_length=3)
    tags: list[str] = Field(default_factory=list)
    input: CaseInput
    expected: Expected
    reference: Reference
    rubric: list[str] = Field(min_length=1, description="criteria for LLM judges")
    metadata: Metadata = Field(default_factory=Metadata)

    @property
    def is_fixable(self) -> bool:
        return self.expected.solved and self.category in (
            "bug_fix_single_file", "bug_fix_multi_file", "pr_quality", "followup_change_request")


class Dataset(Strict):
    schema_version: str = SCHEMA_VERSION
    dataset_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    created: str
    description: str = ""
    cases: list[Case]

    @model_validator(mode="after")
    def unique_ids(self) -> "Dataset":
        seen: set[str] = set()
        for c in self.cases:
            if c.id in seen:
                raise ValueError(f"duplicate case id {c.id}")
            seen.add(c.id)
        return self

    def by_id(self) -> dict[str, Case]:
        return {c.id: c for c in self.cases}


# ---- semantic validation (beyond the schema) ------------------------------------------------

def repo_kind(repo: str) -> str:
    """'bug' for a bundled bug id, 'demo' for demo/<name>, '' when unknown."""
    from app.bugs import BUGS
    from app.repo_loader import demo_names

    if repo in BUGS:
        return "bug"
    if repo.startswith("demo/") and repo.split("/", 1)[1] in demo_names():
        return "demo"
    return ""


def repo_files(repo: str) -> dict[str, str]:
    """Original files of a case's repository (bundled bug -> its target file + test)."""
    from app.bugs import BUGS, test_filename
    from app.repo_loader import load_demo

    if repo in BUGS:
        b = BUGS[repo]
        return {b["target"]: b["buggy"], test_filename(b): b["tests"]}
    return dict(load_demo(repo.split("/", 1)[1]).files)


def semantic_errors(ds: Dataset) -> list[str]:
    """Cross-checks of case contents against the bundled bugs / demo repos. Empty list = consistent."""
    from app.repo_detect import is_test_path

    errs: list[str] = []
    counts: dict[str, int] = {c: 0 for c in CATEGORIES}
    for case in ds.cases:
        counts[case.category] += 1
        cid = case.id
        kind = repo_kind(case.input.repo)
        if not kind:
            errs.append(f"{cid}: unknown repo {case.input.repo!r}")
            continue
        files = repo_files(case.input.repo)
        for p in case.expected.locate_files:
            if p not in files:
                errs.append(f"{cid}: locate file {p} not in {case.input.repo}")
            elif is_test_path(p):
                errs.append(f"{cid}: locate file {p} is a test file")
        for p in case.reference.reference_files:
            if p not in files:
                errs.append(f"{cid}: reference file {p} not in {case.input.repo}")
            elif is_test_path(p):
                errs.append(f"{cid}: reference file {p} is a test file")
        for p in case.reference.reference_files:
            if any(fnmatch.fnmatch(p, g) for g in case.expected.must_not_touch):
                errs.append(f"{cid}: reference file {p} matches must_not_touch")
        if case.is_fixable:
            if not case.reference.reference_diff.strip():
                errs.append(f"{cid}: fixable case without reference_diff")
            if not (case.expected.min_files_changed >= 1):
                errs.append(f"{cid}: fixable case needs min_files_changed >= 1")
            if len(case.reference.reference_files) < case.expected.min_files_changed:
                errs.append(f"{cid}: fewer reference files than min_files_changed")
        if case.input.followup and kind != "demo":
            errs.append(f"{cid}: follow-ups need a demo repo")
        if case.expected.pr and case.expected.pr.fixes_ref and not case.input.issue_ref:
            errs.append(f"{cid}: fixes_ref expected but no issue_ref")
        if case.category == "followup_change_request" and not case.input.followup:
            errs.append(f"{cid}: follow-up category without input.followup")
        if case.category == "safety_guardrails" and case.expected.guard_verdict == "pass" \
                and case.expected.policy_expected == "n/a" and case.expected.security_expected == "n/a":
            errs.append(f"{cid}: safety case checks nothing")
    for cat, minimum in CATEGORY_MINIMUMS.items():
        if counts[cat] < minimum:
            errs.append(f"category {cat}: {counts[cat]} cases < required {minimum}")
    if len(ds.cases) < MIN_TOTAL_CASES:
        errs.append(f"dataset has {len(ds.cases)} cases < {MIN_TOTAL_CASES}")
    return errs


class DatasetError(ValueError):
    pass


def parse_dataset(data: Any) -> Dataset:
    try:
        return Dataset.model_validate(data)
    except Exception as exc:
        raise DatasetError(str(exc)) from exc


def load_dataset(path: Path | str | None = None, *, semantic: bool = True) -> Dataset:
    path = Path(path) if path else GOLDEN_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatasetError(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise DatasetError(f"{path} is not valid JSON: {exc}") from exc
    ds = parse_dataset(data)
    if semantic:
        errs = semantic_errors(ds)
        if errs:
            raise DatasetError("dataset is inconsistent:\n- " + "\n- ".join(errs))
    return ds


@lru_cache(maxsize=4)
def _cached(path: str, mtime: float) -> Dataset:
    return load_dataset(path)


def load_cached(path: Path | str | None = None) -> Dataset:
    p = Path(path) if path else GOLDEN_PATH
    return _cached(str(p), p.stat().st_mtime)


def dataset_hash(path: Path | str | None = None) -> str:
    p = Path(path) if path else GOLDEN_PATH
    return sha256_text(p.read_text(encoding="utf-8"))[:12]


def validate_case_dict(raw: dict[str, Any]) -> tuple[Case | None, list[str]]:
    """For the editor UI: structural + per-case semantic validation of one case."""
    try:
        case = Case.model_validate(raw)
    except Exception as exc:
        return None, [str(exc)]
    ds = Dataset.model_construct(schema_version=SCHEMA_VERSION, dataset_version="0.0.0", created="", cases=[case])
    errs = [e for e in semantic_errors(ds) if not e.startswith("category ") and not e.startswith("dataset has")]
    return (case if not errs else None), errs


def json_schema() -> dict[str, Any]:
    schema = Dataset.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://patchloop.dev/evals/golden.schema.json"
    schema["title"] = "PatchLoop golden dataset"
    return schema


def write_schema(path: Path = SCHEMA_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_schema(), indent=2) + "\n", encoding="utf-8")
