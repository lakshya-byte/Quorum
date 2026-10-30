"""Offline integrity proof of the golden dataset, executed for real in the local sandbox.

For every fixable case:
  * the reference (`correct`) fix makes ALL tests pass (reproducer included for repos),
  * the original code fails at least one test,
  * the `wrong` and `partial` variants rank strictly below `correct`,
  * the reference diff is current, applies to the bundled data, and touches only non-test files.
Plus case-specific checks (reproducers fail on the original and pass on the fix, the existing suite is green where the
case says the suite hides the bug, adversarial patches are well-formed, the unsolvable cases really have no signal).

`python -m evals.integrity [--cases id,id] [--json]` exits 1 on any failure.
"""
from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from evals.common import AGENT_DIR  # noqa: F401
from evals.dataset import Case, Dataset, load_dataset


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class CaseIntegrity:
    case_id: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, bool(ok), detail))


# ---- runners ------------------------------------------------------------------------------

class _Runner:
    """Runs a bundled bug or a demo repo variant in the local sandbox and caches the result."""

    def __init__(self) -> None:
        from app.sandbox import LocalSandbox

        self.sandbox = LocalSandbox(timeout=60, concurrency=4)
        self._cache: dict[tuple, Any] = {}

    async def bug_variant(self, bug_id: str, variant: str) -> dict[str, Any]:
        key = ("bug", bug_id, variant)
        if key not in self._cache:
            from app.bugs import BUGS, files_for
            from app.scoring import parse_unittest, score

            bug = BUGS[bug_id]
            code = bug["buggy"] if variant == "original" else bug[variant]
            _, out = await self.sandbox.run_tests(files_for(bug, code), 60)
            passed, total = parse_unittest(out)
            self._cache[key] = {"passed": passed, "total": total, "score": score(passed, total, bug["buggy"], code),
                                "solved": total > 0 and passed == total, "tail": out[-300:]}
        return self._cache[key]

    async def repo_variant(self, name: str, variant: str, *, reproducer: bool = True, extra: dict | None = None
                           ) -> dict[str, Any]:
        key = ("repo", name, variant, reproducer, json.dumps(extra or {}, sort_keys=True))
        if key not in self._cache:
            from app.repo_eval import build_repo_bug, repo_score, run_tests
            from app.repo_loader import load_demo
            from app.scoring import parse_results

            snap = load_demo(name)
            repro_path = snap.meta.get("repro_path", "tests/test_patchloop_repro.py")
            repro_text = next(iter(snap.meta["repro_text"].values()), "") if reproducer else ""
            bug = build_repo_bug(snap, "integrity", [x["path"] for x in snap.meta["locate"]], uuid.uuid4().hex,
                                 repro_path, repro_text)  # unique id: repo_eval caches results by bug id
            handle = await self.sandbox.checkpoint(snap.files)
            bug["checkpoint"] = handle
            try:
                changed = dict(snap.meta["fixes"].get(variant, {})) if variant != "original" else {}
                changed.update(extra or {})
                code, out = await run_tests(bug, self.sandbox, changed, 60)
            finally:
                await self.sandbox.release(handle)
            passed, total = parse_results(out, code, snap.language)
            self._cache[key] = {"passed": passed, "total": total, "score": repo_score(passed, total, bug, changed),
                                "solved": total > 0 and passed == total, "tail": out[-300:]}
        return self._cache[key]

    async def snippet(self, name: str, code: str) -> tuple[int, str]:
        from app.repo_loader import load_demo

        snap = load_demo(name)
        handle = await self.sandbox.checkpoint(snap.files)
        try:
            return await self.sandbox.run_repo({"_probe.py": code}, "python _probe.py", 30, base=handle)
        finally:
            await self.sandbox.release(handle)


# ---- checks -------------------------------------------------------------------------------

def _diff_current(case: Case) -> tuple[bool, str]:
    from evals.build_golden import derive_bug, derive_demo

    d = derive_bug(case.input.repo) if "/" not in case.input.repo else derive_demo(case.input.repo.split("/", 1)[1])
    ok = d["reference_diff"] == case.reference.reference_diff and sorted(d["reference_files"]) == \
        sorted(case.reference.reference_files)
    return ok, "reference diff matches a fresh derivation" if ok else "reference diff is stale: rebuild the dataset"


def _diff_files(diff: str) -> list[str]:
    return [line.split(" b/", 1)[1] for line in diff.splitlines() if line.startswith("diff --git ")]


def _ranks_below(candidate: dict, correct: dict) -> bool:
    return (candidate["solved"], candidate["score"]) < (correct["solved"], correct["score"])


async def _check_fixable(case: Case, run: _Runner, rep: CaseIntegrity) -> None:
    from app.repo_detect import is_test_path

    repo = case.input.repo
    if "/" not in repo:
        original, correct = await run.bug_variant(repo, "original"), await run.bug_variant(repo, "correct")
        variants = {v: await run.bug_variant(repo, v) for v in ("partial", "wrong")}
    else:
        name = repo.split("/", 1)[1]
        original, correct = await run.repo_variant(name, "original"), await run.repo_variant(name, "correct")
        variants = {v: await run.repo_variant(name, v) for v in ("partial", "wrong")
                    if v in _fix_variants(name)}
    rep.add("reference_fix_passes_all_tests", correct["solved"], f"{correct['passed']}/{correct['total']} pass")
    rep.add("original_fails_at_least_one_test", original["total"] > 0 and original["passed"] < original["total"],
            f"{original['passed']}/{original['total']} pass on the original")
    for name, res in variants.items():
        rep.add(f"{name}_ranks_below_correct", _ranks_below(res, correct),
                f"{name}: {res['passed']}/{res['total']} score {res['score']:.3f} < correct {correct['score']:.3f}")
    files = _diff_files(case.reference.reference_diff)
    rep.add("reference_diff_non_test_files_only", bool(files) and not any(is_test_path(f) for f in files), ", ".join(files))
    rep.add("reference_diff_not_in_must_not_touch",
            not any(fnmatch.fnmatch(f, g) for f in files for g in case.expected.must_not_touch), "")
    if case.expected.max_files_changed:
        rep.add("file_count_within_expected",
                case.expected.min_files_changed <= len(files) <= case.expected.max_files_changed,
                f"{len(files)} files, expected {case.expected.min_files_changed}..{case.expected.max_files_changed}")
    ok, detail = _diff_current(case)
    rep.add("reference_diff_is_current", ok, detail)


def _fix_variants(name: str) -> list[str]:
    from app.repo_loader import load_demo

    return [v for v, files in load_demo(name).meta["fixes"].items() if files]


async def _check_locator(case: Case, rep: CaseIntegrity) -> None:
    from app.repo_loader import load_demo

    snap = load_demo(case.input.repo.split("/", 1)[1])
    truth = {x["path"] for x in snap.meta["locate"]}
    rep.add("locate_truth_equals_meta_json", truth == set(case.expected.locate_files), ", ".join(sorted(truth)))
    rep.add("locate_truth_exists_and_not_test", all(p in snap.files for p in truth), "")
    non_truth_sources = [p for p in snap.files if p.endswith(".py") and p not in truth and "tests/" not in p]
    rep.add("has_distractor_files", bool(non_truth_sources), f"{len(non_truth_sources)} other source files")


async def _check_repro(case: Case, run: _Runner, rep: CaseIntegrity) -> None:
    name = case.input.repo.split("/", 1)[1]
    suite = await run.repo_variant(name, "original", reproducer=False)
    orig = await run.repo_variant(name, "original", reproducer=True)
    fixed = await run.repo_variant(name, "correct", reproducer=True)
    rep.add("reproducer_fails_on_original", orig["total"] > suite["total"] and orig["passed"] < orig["total"],
            f"with reproducer {orig['passed']}/{orig['total']} (suite alone {suite['passed']}/{suite['total']})")
    rep.add("reproducer_passes_on_reference_fix", fixed["solved"], f"{fixed['passed']}/{fixed['total']}")
    if "existing-suite-green" in case.tags:
        rep.add("existing_suite_green_on_original", suite["solved"], f"{suite['passed']}/{suite['total']} pass")


async def _check_unsolvable(case: Case, run: _Runner, rep: CaseIntegrity) -> None:
    from app.repo_agents import heuristic_locate
    from app.repo_loader import load_demo

    name = case.input.repo.split("/", 1)[1]
    suite = await run.repo_variant(name, "original", reproducer=False)
    if case.metadata.fake_script == "no_reproducer":
        rep.add("existing_suite_green_on_original", suite["solved"], f"{suite['passed']}/{suite['total']}")
    if case.metadata.fake_script == "no_locator_hint":
        hits = heuristic_locate(case.input.full_text, load_demo(name).files)
        rep.add("no_source_file_matches_task", not hits, f"keyword locator returned {[h['path'] for h in hits]}")
    if case.metadata.fake_script == "no_reproducer":
        code, out = await run.snippet(name, "from booking.calendar import Calendar, ConflictError\n"
                                            "c = Calendar(); c.book(9, 11)\n"
                                            "try:\n    c.book(10, 12)\nexcept ConflictError:\n    print('CONFLICT')\n")
        rep.add("claimed_bug_does_not_reproduce", "CONFLICT" in out, out.strip()[-120:])


async def _check_safety(case: Case, run: _Runner, rep: CaseIntegrity) -> None:
    patch = case.input.adversarial_patch
    if not patch:
        return
    name = case.input.repo.split("/", 1)[1]
    good = {p: t for p, t in patch.items() if p.endswith(".py") and ".." not in p and not p.startswith(".")}
    for p, text in good.items():
        try:
            compile(text, p, "exec")
            rep.add(f"patch_parses:{p}", True)
        except SyntaxError as exc:
            rep.add(f"patch_parses:{p}", False, str(exc))
    res = await run.repo_variant(name, "original", extra=good)
    if case.expected.policy_expected == "block" and "path-traversal" in case.tags:
        rep.add("legit_part_of_patch_would_pass_tests", res["solved"], f"{res['passed']}/{res['total']}")
    if case.expected.security_expected == "block":
        rep.add("patch_passes_all_tests", res["solved"], f"{res['passed']}/{res['total']}")
        from app.sandbox import LocalSandbox  # noqa: F401
        from app.security import bandit_available, security_verdict

        if not bandit_available():
            rep.add("bandit_available", False, "bandit is not installed")
        else:
            from app.repo_loader import load_demo

            snap = load_demo(name)
            path = next(iter(good))
            before = await run.sandbox.scan(path, snap.files[path])
            after = await run.sandbox.scan(path, good[path])
            verdict = security_verdict(before, after)
            rep.add("bandit_flags_new_finding", not verdict["ok"],
                    ", ".join(f"{f['test_id']}/{f['severity']}" for f in verdict["new_findings"]) or "no new finding")


async def check_case(case: Case, run: _Runner) -> CaseIntegrity:
    rep = CaseIntegrity(case.id)
    try:
        if case.category in ("bug_fix_single_file", "bug_fix_multi_file", "pr_quality", "followup_change_request") \
                or (case.category == "safety_guardrails" and case.expected.solved):
            await _check_fixable(case, run, rep)
        elif case.category == "locator_retrieval":
            await _check_locator(case, rep)
        elif case.category == "reproducer_quality":
            await _check_repro(case, run, rep)
            await _check_fixable(case, run, rep)
        elif case.category == "unsolvable_or_underspecified":
            await _check_unsolvable(case, run, rep)
        elif case.category == "safety_guardrails":
            await _check_safety(case, run, rep)
        if case.category == "followup_change_request":
            rep.add("followup_branch_looks_like_patchloop_branch", case.input.followup.pr_branch.startswith("patchloop/"),
                    case.input.followup.pr_branch)
    except Exception as exc:  # an integrity run must report, not crash
        rep.add("integrity_check_raised", False, f"{type(exc).__name__}: {exc}")
    return rep


async def run_integrity(ds: Dataset | None = None, case_ids: list[str] | None = None,
                        on_case: Any = None) -> dict[str, Any]:
    ds = ds or load_dataset()
    cases = [c for c in ds.cases if not case_ids or c.id in case_ids]
    run, t0, reports = _Runner(), time.monotonic(), []
    for case in cases:
        rep = await check_case(case, run)
        reports.append(rep)
        if on_case:
            on_case(rep)
    failed = [r for r in reports if not r.ok]
    return {"ok": not failed, "cases": len(reports), "checks": sum(len(r.checks) for r in reports),
            "failed_cases": [r.case_id for r in failed], "seconds": round(time.monotonic() - t0, 1),
            "dataset_version": ds.dataset_version, "reports": [{"case_id": r.case_id, "ok": r.ok,
                                                                "checks": [asdict(c) for c in r.checks]} for r in reports]}


def format_report(result: dict[str, Any], verbose: bool = False) -> str:
    lines = []
    for r in result["reports"]:
        lines.append(f"[{'ok' if r['ok'] else 'FAIL'}] {r['case_id']}  ({sum(c['ok'] for c in r['checks'])}/{len(r['checks'])})")
        for c in r["checks"]:
            if verbose or not c["ok"]:
                lines.append(f"      {'+' if c['ok'] else '-'} {c['name']}: {c['detail']}")
    lines.append(f"\nintegrity {'PASSED' if result['ok'] else 'FAILED'}: {result['cases']} cases, "
                 f"{result['checks']} checks, {result['seconds']}s")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.integrity")
    ap.add_argument("--cases", default="", help="comma separated case ids")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    result = asyncio.run(run_integrity(case_ids=[c for c in args.cases.split(",") if c]))
    print(json.dumps(result, indent=2) if args.json else format_report(result, args.verbose))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
