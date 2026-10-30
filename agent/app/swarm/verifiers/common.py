"""Helpers shared by the verifiers: workspace state hashing, dependency install, test running with a result cache."""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.repo_detect import is_test_path
from app.swarm.repo_map import RepoMap, build_repo_map
from app.swarm.verifiers.testparse import parse_any
from app.swarm.verifiers.types import Baseline

TEST_TIMEOUT = 300
BUILD_TIMEOUT = 300
INSTALL_TIMEOUT = 420


async def current_files(ws: Any, baseline: Baseline) -> dict[str, str]:
    """Text of every non-generated file now. Falls back to baseline + ws.changed() for foreign workspaces."""
    if hasattr(ws, "snapshot"):
        return await ws.snapshot()
    files = dict(baseline.files)
    for path, text in (await ws.changed()).items():
        if text is None:
            files.pop(path, None)
        else:
            files[path] = text
    return files


def state_hash(files: dict[str, str], extra: str = "") -> str:
    h = hashlib.sha256(extra.encode())
    for p in sorted(files):
        h.update(b"\0" + p.encode() + b"\0" + files[p].encode("utf-8", errors="replace"))
    return h.hexdigest()


def repo_map_of(baseline: Baseline, files: dict[str, str] | None = None) -> RepoMap:
    if files is None:
        if baseline.repo_map is None:
            baseline.repo_map = build_repo_map(baseline.files)
        return baseline.repo_map
    return build_repo_map(files)


async def ensure_installed(ws: Any, rm: RepoMap) -> tuple[bool, str]:
    """Install node dependencies once per workspace lineage. (ok, detail). Python/Go need no install here."""
    install = rm.commands.get("install", "")
    if not install or not install.split()[0] in ("npm", "pnpm", "yarn"):
        return True, ""
    if getattr(ws, "_pl_installed", False):
        return True, ""
    exists = getattr(ws, "exists", None)
    if exists is not None and await exists("node_modules"):
        ws._pl_installed = True  # type: ignore[attr-defined]
        return True, ""
    res = await ws.exec(install, timeout=INSTALL_TIMEOUT)
    if res.code == 0:
        ws._pl_installed = True  # type: ignore[attr-defined]
        return True, ""
    return False, f"`{install}` failed (exit {res.code}): {res.stdout_tail[-300:]}"


def test_plan(rm: RepoMap) -> tuple[str, str]:
    """(framework, command) that prints per-test results we can parse. ("", "") when the repo has no tests."""
    fw = rm.frameworks
    cmds = rm.commands
    has_py_tests = any(t.endswith(".py") for t in rm.tests)
    if rm.primary_language == "python" or has_py_tests:
        if "pytest" in fw:
            return "pytest", "python -m pytest -v -p no:cacheprovider --no-header"
        if rm.tests or cmds.get("test"):
            return "unittest", 'python -m unittest discover -s . -t . -p "test*.py" -v'
    if "vitest" in fw:
        return "vitest", "npx vitest run --reporter=json"
    if "jest" in fw:
        return "jest", "npx jest --json"
    if "go" in fw and any(t.endswith("_test.go") for t in rm.tests):
        return "go", "go test -v ./..."
    if cmds.get("test"):
        return "generic", cmds["test"]
    return "", ""


@dataclass
class TestRun:
    __test__ = False  # not a pytest class
    code: int
    output: str
    results: dict[str, str] = field(default_factory=dict)
    command: str = ""
    framework: str = ""
    ms: int = 0
    cached: bool = False

    @property
    def passing(self) -> set[str]:
        return {k for k, v in self.results.items() if v == "pass"}

    @property
    def failing(self) -> set[str]:
        return {k for k, v in self.results.items() if v == "fail"}


_CACHE: OrderedDict[str, TestRun] = OrderedDict()
CACHE_MAX = 64


def clear_caches() -> None:
    _CACHE.clear()


async def run_tests(ws: Any, baseline: Baseline, files: dict[str, str], *, rm: RepoMap | None = None) -> TestRun | None:
    """Run the suite once per distinct workspace state (cached). None when the repo has no runnable tests."""
    rm = rm or build_repo_map(files)
    fw, cmd = test_plan(rm)
    if not cmd:
        return None
    key = state_hash(files, cmd)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        hit = _CACHE[key]
        return TestRun(hit.code, hit.output, hit.results, hit.command, hit.framework, hit.ms, cached=True)
    ok, why = await ensure_installed(ws, rm)
    if not ok:
        return TestRun(1, why, {}, cmd, fw)
    t0 = time.monotonic()
    res = await ws.exec(cmd, timeout=TEST_TIMEOUT)
    known = {p for p in files if is_test_path(p) or p.endswith((".js", ".jsx", ".ts", ".tsx", ".py", ".go"))}
    parsed = parse_any(res.stdout_tail, fw, known)
    run = TestRun(res.code, res.stdout_tail, parsed, cmd, fw, int((time.monotonic() - t0) * 1000))
    if not res.stdout_tail.startswith(("SANDBOX_ERROR", "COMMAND_DENIED", "TIMEOUT")):
        _CACHE[key] = run
        if len(_CACHE) > CACHE_MAX:
            _CACHE.popitem(last=False)
    return run


def summarise_ids(ids: set[str] | list[str], n: int = 4) -> str:
    items = sorted(ids)
    more = f" (+{len(items) - n} more)" if len(items) > n else ""
    return ", ".join(i[-70:] for i in items[:n]) + more
