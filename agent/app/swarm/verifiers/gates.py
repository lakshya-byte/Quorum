"""Deterministic verifiers (everything except the ui_* family, which lives in ui.py)."""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import PurePosixPath
from typing import Any

from app.repo_detect import is_test_path
from app.policy import path_violation
from app.swarm.repo_map import CODE_LANGS, RepoMap, build_repo_map
from app.swarm.verifiers import surface as surf
from app.swarm.verifiers.common import (BUILD_TIMEOUT, TestRun, ensure_installed, repo_map_of, run_tests,
                                        summarise_ids)
from app.swarm.verifiers.registry import Ctx, register, result, skip
from app.swarm.verifiers.scan import secret_hits, security_scan
from app.swarm.verifiers.testparse import test_file_of
from app.swarm.verifiers.types import Baseline, Criterion, VerifyResult

MAX_POLICY_FILES = 40
MAX_CHANGED_FILE_BYTES = 1_000_000


# ---- build ------------------------------------------------------------------------------------------------

def build_commands(rm: RepoMap) -> list[str]:
    cmds: list[str] = []
    py = sorted({p for p, f in rm.files.items() if f.lang == "python"})
    if py:
        targets = sorted({p.split("/")[0] for p in py if "/" in p} | {p for p in py if "/" not in p})
        cmds.append("python -m compileall -q " + " ".join(targets[:40]))
    if rm.commands.get("build") and rm.commands["build"].split()[0] in ("npm", "pnpm", "yarn", "go", "cargo", "make", "mvn"):
        cmds.append(rm.commands["build"])
    elif not rm.commands.get("build") and rm.commands.get("typecheck") and any(
            f.lang in ("typescript", "javascript") for f in rm.files.values()):
        cmds.append(rm.commands["typecheck"])
    return cmds


async def run_build(ws: Any, rm: RepoMap) -> tuple[str, str, list[str]]:
    """(status pass|fail|skip, detail, commands)."""
    cmds = build_commands(rm)
    if not cmds:
        return "skip", "no build script or compilable sources", []
    ok, why = await ensure_installed(ws, rm)
    if not ok:
        return "fail", why, cmds
    for cmd in cmds:
        res = await ws.exec(cmd, timeout=BUILD_TIMEOUT)
        if res.code != 0:
            return "fail", f"`{cmd}` failed (exit {res.code}): {res.stdout_tail[-400:].strip()}", cmds
    return "pass", "build ok: " + "; ".join(f"`{c}`" for c in cmds), cmds


@register("build")
async def v_build(c: Criterion, ctx: Ctx) -> VerifyResult:
    status, detail, _ = await run_build(ctx.ws, await ctx.repo_map())
    return result(c, status, detail)


# ---- tests ------------------------------------------------------------------------------------------------

async def _run(ctx: Ctx) -> TestRun | None:
    return await run_tests(ctx.ws, ctx.baseline, await ctx.files(), rm=await ctx.repo_map())


@register("tests")
async def v_tests(c: Criterion, ctx: Ctx) -> VerifyResult:
    run = await _run(ctx)
    if run is None:
        return skip(c, "no test command detected")
    if run.code == 0 and (run.results or run.output):
        n = len(run.results)
        return result(c, "pass", f"{n or 'all'} tests pass (`{run.command}`)", meta_total=n)
    if run.results and run.failing:
        return result(c, "fail", f"{len(run.failing)} failing: {summarise_ids(run.failing)}")
    return result(c, "fail", f"`{run.command}` exited {run.code}: {run.output[-300:].strip()}")


@register("no_regression")
async def v_no_regression(c: Criterion, ctx: Ctx) -> VerifyResult:
    base = ctx.baseline.tests
    if base.get("status") in (None, "none"):
        return skip(c, "the original repo has no runnable tests")
    run = await _run(ctx)
    if run is None:
        return result(c, "fail", "tests existed originally but no test command is detected now")
    before = ctx.baseline.passing_tests
    if not before:
        if base.get("code") == 0:
            return result(c, "pass" if run.code == 0 else "fail",
                          "per-test results were not parseable; compared exit codes only "
                          f"(original 0, now {run.code})")
        return skip(c, "the original suite had no passing tests to protect")
    now = run.passing
    missing = before - now
    if missing:
        failing = missing & run.failing
        gone = missing - set(run.results)
        return result(c, "fail", f"{len(missing)} of {len(before)} originally passing tests no longer pass "
                                 f"({len(failing)} failing, {len(gone)} missing/deleted): {summarise_ids(missing)}",
                      missing=sorted(missing)[:50])
    return result(c, "pass", f"all {len(before)} originally passing tests still pass ({len(now)} pass now)")


# ---- spec tests: repro / acceptance / characterization ------------------------------------------------------

async def install_spec_files(ctx: Ctx, files: dict[str, str]) -> None:
    put = getattr(ctx.ws, "put_trusted", None) or ctx.ws.write
    for path, text in files.items():
        await put(path, text)
    await ctx.files(refresh=True)


async def _spec_tests(c: Criterion, ctx: Ctx, label: str) -> VerifyResult:
    spec: dict[str, str] = dict(c.params.get("files") or {})
    wanted = list(c.params.get("tests") or spec)
    if not wanted:
        return skip(c, f"{label} criterion has no test files")
    if spec:
        await install_spec_files(ctx, spec)
    run = await _run(ctx)
    if run is None:
        return result(c, "fail", "no test command is detected, so the " + label + " tests cannot run")
    known = set(await ctx.files())
    mine = {tid: st for tid, st in run.results.items() if test_file_of(tid, known) in wanted}
    if not mine:
        return result(c, "fail", f"no tests from {', '.join(wanted)} were discovered/run (exit {run.code}): "
                                 f"{run.output[-240:].strip()}")
    bad = {t for t, st in mine.items() if st != "pass"}
    if bad:
        return result(c, "fail", f"{len(bad)} of {len(mine)} {label} tests fail: {summarise_ids(bad)}",
                      failing=sorted(bad)[:50], total=len(mine))
    return result(c, "pass", f"all {len(mine)} {label} tests pass", total=len(mine))


@register("repro")
async def v_repro(c: Criterion, ctx: Ctx) -> VerifyResult:
    return await _spec_tests(c, ctx, "reproducer")


@register("acceptance_tests")
async def v_acceptance(c: Criterion, ctx: Ctx) -> VerifyResult:
    return await _spec_tests(c, ctx, "acceptance")


@register("characterization")
async def v_characterization(c: Criterion, ctx: Ctx) -> VerifyResult:
    return await _spec_tests(c, ctx, "characterization")


# ---- policy / security / secrets ----------------------------------------------------------------------------

async def _changes(ctx: Ctx) -> dict[str, str | None]:
    return await ctx.ws.changed()


@register("policy")
async def v_policy(c: Criterion, ctx: Ctx) -> VerifyResult:
    changed = await _changes(ctx)
    originals = ctx.baseline.files
    allow_tests = bool(c.params.get("allow_tests")) or c.params.get("task_type") == "tests"
    max_files = int(c.params.get("max_files", MAX_POLICY_FILES))
    protected = list(c.params.get("protected_globs") or [])
    spec_paths = set((c.params.get("spec_files") or {}))
    problems: list[str] = []
    if not changed:
        return result(c, "fail", "no files changed")
    if len(changed) > max_files:
        problems.append(f"{len(changed)} files changed (max {max_files})")
    for path, text in sorted(changed.items()):
        bad = path_violation(path)
        if bad:
            problems.append(bad)
            continue
        if any(fnmatch.fnmatch(path, g) for g in protected):
            problems.append(f"{path}: protected path")
        if path in originals and is_test_path(path) and path not in spec_paths and not allow_tests:
            problems.append(f"{path}: existing test file {'deleted' if text is None else 'modified'}")
        elif text is not None and len(text.encode("utf-8", errors="replace")) > MAX_CHANGED_FILE_BYTES:
            problems.append(f"{path}: file larger than 1 MB")
    if not allow_tests and "package.json" in changed and "package.json" in originals and changed["package.json"]:
        try:
            old = json.loads(originals["package.json"]).get("scripts", {}).get("test")
            new = json.loads(changed["package.json"]).get("scripts", {}).get("test")
            if old != new:
                problems.append(f"package.json: the test script changed ({old!r} -> {new!r})")
        except ValueError:
            problems.append("package.json: not valid JSON")
    if problems:
        return result(c, "fail", "; ".join(problems[:6]) + (f" (+{len(problems) - 6} more)" if len(problems) > 6 else ""),
                      violations=problems)
    return result(c, "pass", f"{len(changed)} changed file(s), none protected; existing tests untouched")


@register("security")
async def v_security(c: Criterion, ctx: Ctx) -> VerifyResult:
    changed = await _changes(ctx)
    originals = ctx.baseline.files
    findings: list[dict] = []
    scanned = 0
    unscannable_py = False
    for path, text in sorted(changed.items()):
        if text is None or is_test_path(path):
            continue
        fs, ran = await security_scan(path, originals.get(path), text)
        if ran:
            scanned += 1
        elif path.endswith(".py"):
            unscannable_py = True
        findings += fs
    if findings:
        shown = "; ".join(f"{f['file']}:{f.get('line')} {f['test_id']} {f['severity']} {f['text'][:60]}" for f in findings[:4])
        return result(c, "fail", f"{len(findings)} new medium/high finding(s): {shown}", findings=findings[:20])
    if unscannable_py and not scanned:
        return skip(c, "bandit is not installed, Python files could not be scanned")
    return result(c, "pass", f"no new medium/high findings in {scanned} scanned file(s)" +
                  (" (bandit unavailable for some Python files)" if unscannable_py else ""))


@register("secrets")
async def v_secrets(c: Criterion, ctx: Ctx) -> VerifyResult:
    changed = await _changes(ctx)
    originals = ctx.baseline.files
    hits: list[str] = []
    for path, text in sorted(changed.items()):
        if text is not None:
            hits += secret_hits(path, originals.get(path), text)
    if hits:
        return result(c, "fail", f"{len(hits)} secret-looking value(s) added: " + "; ".join(hits[:4]), hits=hits[:20])
    return result(c, "pass", f"no secret-looking strings in added lines of {len(changed)} changed file(s)")


# ---- api surface ----------------------------------------------------------------------------------------------

def default_surface_modules(rm: RepoMap, files: dict[str, str]) -> list[str]:
    py = [p for p, f in rm.files.items() if f.lang == "python" and not f.is_test and "/" in p
          and (p.endswith("__init__.py") or not PurePosixPath(p).name.startswith("_"))]
    if py:
        return sorted(set(py))
    pkg = files.get("package.json")
    out = []
    if pkg:
        try:
            main = json.loads(pkg).get("main")
            if isinstance(main, str) and main.lstrip("./") in files:
                out.append(main.lstrip("./"))
        except ValueError:
            pass
    out += [p for p in files if re.match(r"^(src/)?index\.(ts|tsx|js|jsx|mjs)$", p)]
    return sorted(set(out))


@register("api_surface")
async def v_api_surface(c: Criterion, ctx: Ctx) -> VerifyResult:
    before_files = ctx.baseline.files
    after_files = await ctx.files()
    rm0 = repo_map_of(ctx.baseline)
    modules = list(c.params.get("modules") or default_surface_modules(rm0, before_files))
    if not modules:
        return skip(c, "no public modules detected for an API surface comparison")
    ignore = set(c.params.get("ignore") or [])
    problems: list[str] = []
    compared = 0
    for mod in modules:
        before = surf.surface_of(before_files, mod)
        if before is None:
            continue
        before = {k: v for k, v in before.items() if k not in ignore}
        if not before:
            continue
        compared += len(before)
        after = surf.surface_of(after_files, mod)
        problems += [f"{mod}: {p}" for p in surf.diff_surface(before, None if after is None else
                                                              {k: v for k, v in after.items() if k not in ignore})]
    if compared == 0:
        return skip(c, "the original modules export no public symbols")
    if problems:
        return result(c, "fail", f"public API changed ({len(problems)}): " + "; ".join(problems[:5]), problems=problems[:30])
    return result(c, "pass", f"public API surface unchanged ({compared} exported symbols across {len(modules)} module(s))")


# ---- lint / typecheck -------------------------------------------------------------------------------------------

def lint_tools(rm: RepoMap) -> list[tuple[str, str, str]]:
    """(tool name, command, counter) for each static checker applicable to the repo."""
    tools: list[tuple[str, str, str]] = []
    if rm.primary_language == "python" or any(f.lang == "python" for f in rm.files.values()):
        tools.append(("ruff", "python -m ruff check --output-format=concise .", "ruff"))
        if rm.commands.get("typecheck", "").startswith("python -m mypy"):
            tools.append(("mypy", rm.commands["typecheck"], "mypy"))
    if rm.commands.get("lint", "").split(" ")[0] in ("npm", "pnpm", "yarn"):
        tools.append(("lint", rm.commands["lint"], "eslint"))
    if rm.commands.get("typecheck", "").startswith(("npx tsc", "npm", "pnpm", "yarn")):
        tools.append(("typecheck", rm.commands["typecheck"], "tsc"))
    if rm.commands.get("lint", "").startswith("go vet"):
        tools.append(("go vet", rm.commands["lint"], "govet"))
    return tools


def count_issues(counter: str, code: int, output: str) -> int | None:
    """Issue count, or None when the tool itself is unavailable."""
    if "No module named" in output or "command not found" in output or output.startswith("COMMAND_DENIED"):
        return None
    if counter == "ruff":
        return len(re.findall(r"^\S+:\d+:\d+: ", output, re.M))
    if counter == "mypy":
        return len(re.findall(r": error:", output))
    if counter == "tsc":
        return len(re.findall(r"error TS\d+", output))
    if counter == "eslint":
        n = len(re.findall(r"^\s*\d+:\d+\s+(?:error|warning)\b", output, re.M))
        return n or (0 if code == 0 else 1)
    if counter == "govet":
        return len([ln for ln in output.splitlines() if ln.strip() and not ln.startswith("#")]) if code else 0
    return 0 if code == 0 else 1


async def run_lint(ws: Any, rm: RepoMap) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    tools = lint_tools(rm)
    if not tools:
        return out
    await ensure_installed(ws, rm)
    for name, cmd, counter in tools:
        res = await ws.exec(cmd, timeout=BUILD_TIMEOUT)
        n = count_issues(counter, res.code, res.stdout_tail)
        if n is not None:
            out[name] = {"count": n, "command": cmd}
    return out


@register("lint_typecheck")
async def v_lint(c: Criterion, ctx: Ctx) -> VerifyResult:
    before = ctx.baseline.lint
    if not before:
        return skip(c, "no lint/typecheck tool available for this repo (ruff/mypy/eslint/tsc not found or not configured)")
    after = await run_lint(ctx.ws, await ctx.repo_map())
    worse = []
    for tool, b in before.items():
        a = after.get(tool)
        if a is None:
            worse.append(f"{tool}: tool no longer runs")
        elif a["count"] > b["count"]:
            worse.append(f"{tool}: {b['count']} -> {a['count']} issues")
    summary = ", ".join(f"{t} {b['count']}->{after.get(t, {}).get('count', '?')}" for t, b in before.items())
    if worse:
        return result(c, "fail", "lint/typecheck got worse: " + "; ".join(worse))
    return result(c, "pass", "no worse than baseline: " + summary)


# ---- complexity metric --------------------------------------------------------------------------------------------

def metric_value(rm: RepoMap, metric: str, patterns: list[str]) -> float | None:
    def match(p: str) -> bool:
        return not patterns or any(fnmatch.fnmatch(p, g) or p == g for g in patterns)
    files = [f for p, f in rm.files.items() if match(p) and f.lang in CODE_LANGS and not f.is_test]
    if metric == "file_lines" or metric == "max_file_lines":
        return float(max((f.lines for f in files), default=0)) if files else None
    if metric == "total_lines":
        return float(sum(f.lines for f in files))
    funcs = [m for f in files for m in f.functions]
    if metric == "max_function_lines":
        return float(max((m.lines for m in funcs), default=0))
    if metric == "max_function_complexity":
        return float(max((m.complexity for m in funcs), default=0))
    if metric == "total_complexity":
        return float(sum(m.complexity for m in funcs))
    if metric == "import_cycles":
        return float(len([cy for cy in rm.cycles if not patterns or any(match(p) for p in cy)]))
    return None


_OPS = {"<=": lambda a, b: a <= b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
        "==": lambda a, b: a == b}


@register("complexity_metric")
async def v_complexity(c: Criterion, ctx: Ctx) -> VerifyResult:
    metric = c.params.get("metric", "max_file_lines")
    patterns = list(c.params.get("paths") or [])
    before_rm = repo_map_of(ctx.baseline)
    after_rm = await ctx.repo_map()
    b, a = metric_value(before_rm, metric, patterns), metric_value(after_rm, metric, patterns)
    if b is None or a is None:
        return skip(c, f"metric {metric!r} unknown or no matching files")
    target = c.params.get("target")
    ok = True
    parts = [f"{metric}{' ' + ','.join(patterns) if patterns else ''}: {b:g} -> {a:g}"]
    if target:
        op, val = target.get("op", "<="), float(target["value"])
        ok = _OPS[op](a, val)
        parts.append(f"target {op} {val:g}: {'met' if ok else 'NOT met'}")
    lower_is_better = (target or {}).get("op", "<=") in ("<=", "<") if target else True
    improved = a < b if lower_is_better else a > b
    if c.params.get("require_improvement", True) and not improved:
        ok = False
        parts.append("no improvement over the original")
    return result(c, "pass" if ok else "fail", "; ".join(parts), score=a, before=b, after=a)


# ---- command / benchmark -----------------------------------------------------------------------------------------

@register("command")
async def v_command(c: Criterion, ctx: Ctx) -> VerifyResult:
    cmd = c.params.get("cmd", "")
    if not cmd:
        return skip(c, "command criterion has no cmd")
    res = await ctx.ws.exec(cmd, timeout=int(c.params.get("timeout", 120)))
    want = int(c.params.get("expect_code", 0))
    if res.stdout_tail.startswith("COMMAND_DENIED"):
        return result(c, "fail", res.stdout_tail[:300])
    if res.code == want:
        return result(c, "pass", f"`{cmd}` exited {res.code} in {res.duration_ms} ms")
    return result(c, "fail", f"`{cmd}` exited {res.code} (expected {want}): {res.stdout_tail[-300:].strip()}")


@register("benchmark")
async def v_benchmark(c: Criterion, ctx: Ctx) -> VerifyResult:
    cmd, rx = c.params.get("cmd", ""), c.params.get("regex", r"([0-9]+(?:\.[0-9]+)?)")
    if not cmd or "threshold" not in c.params:
        return skip(c, "benchmark criterion needs cmd and threshold")
    res = await ctx.ws.exec(cmd, timeout=int(c.params.get("timeout", 300)))
    if res.code != 0:
        return result(c, "fail", f"`{cmd}` exited {res.code}: {res.stdout_tail[-200:].strip()}")
    m = re.search(rx, res.stdout_tail)
    if not m:
        return result(c, "fail", f"could not read a number with /{rx}/ from the output")
    value, thr = float(m.group(1)), float(c.params["threshold"])
    higher = c.params.get("direction", "max") == "min"  # "min": value must be >= threshold
    ok = value >= thr if higher else value <= thr
    return result(c, "pass" if ok else "fail", f"measured {value:g} ({'>=' if higher else '<='} {thr:g} required)", score=value)


# ---- advisory ----------------------------------------------------------------------------------------------------

@register("advisory_vision", "advisory_rubric")
async def v_advisory(c: Criterion, ctx: Ctx) -> VerifyResult:
    judge = ctx.judge or c.params.get("judge")
    if judge is None:
        return result(c, "skip", "needs_judge", advisory=True)
    context: dict[str, Any] = {"rubric": c.params.get("rubric") or c.description, "kind": c.kind}
    ui_before = ctx.baseline.ui.get("shots") or {}
    context["before_screenshots"] = dict(ui_before)
    context["changed_files"] = sorted((await ctx.ws.changed()).keys())[:50]
    arts = []
    if c.kind == "advisory_vision":
        try:
            from app.swarm.verifiers.ui import add_shots, ui_state
            state = await ui_state(ctx.ws, await ctx.repo_map(), await ctx.files())
            if state.get("status") == "ok":
                context["after_screenshots"] = state["probe"].get("shots", {})
                arts = add_shots(ctx.store, "before", ui_before) + add_shots(ctx.store, "after", context["after_screenshots"])
            else:
                return result(c, "skip", "needs_judge: no screenshots available (" + state.get("detail", "") + ")")
        except Exception as exc:  # screenshots are best effort for an advisory criterion
            return result(c, "skip", f"needs_judge: screenshots failed ({type(exc).__name__})")
    try:
        verdict = await judge(c.kind, c, context)
    except Exception as exc:
        return result(c, "skip", f"judge failed: {type(exc).__name__}")
    score = verdict.get("score")
    return result(c, "advisory", str(verdict.get("rationale", ""))[:500], score=float(score) if score is not None else None,
                  artifacts=arts)
