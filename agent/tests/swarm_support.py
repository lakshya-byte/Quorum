"""Test doubles for builder B's interfaces (contract section 6): a tmpdir Workspace that really runs commands, fake
verifiers with real before/after behaviour, an in-memory ArtifactStore, and small fixture repos + scripted scripts.
Only the LLM is scripted; everything the swarm core does with these is the real code path."""
from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings
from app.swarm.deps import SwarmDeps
from app.swarm.fake_swarm import FakeSwarm
from app.swarm.types import SwarmCtx

SKIP_DIRS = {"__pycache__", ".pytest_cache"}


@dataclass
class ExecResult:
    code: int
    stdout_tail: str
    duration_ms: int


class TmpWorkspace:
    """Local isolated subprocess workspace (minimal env). Implements the section 6 Workspace protocol."""

    isolation = "local"
    instances: list["TmpWorkspace"] = []

    def __init__(self, files: dict[str, str], checkpoint: dict[str, str] | None = None) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="plws-"))
        self.released = False
        for p, t in files.items():
            self._put(p, t)
        self.checkpoint = dict(checkpoint if checkpoint is not None else files)
        self.exec_log: list[str] = []
        TmpWorkspace.instances.append(self)

    def _put(self, path: str, text: str) -> None:
        target = (self.root / path).resolve()
        if self.root.resolve() not in target.parents:
            raise PermissionError(f"path escape: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def tree(self) -> dict[str, str]:
        out = {}
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and not (set(p.relative_to(self.root).parts) & SKIP_DIRS) and p.suffix != ".pyc":
                out[p.relative_to(self.root).as_posix()] = p.read_text(encoding="utf-8")
        return out

    async def list_dir(self, path: str = ".") -> list[str]:
        base = (self.root / path).resolve()
        if self.root.resolve() not in [base, *base.parents]:
            raise PermissionError("escape")
        return sorted(f"{c.name}/" if c.is_dir() else c.name for c in base.iterdir() if c.name not in SKIP_DIRS)

    async def read(self, path: str, start: int | None = None, end: int | None = None) -> str:
        text = (self.root / path).read_text(encoding="utf-8")
        if start is None and end is None:
            return text
        lines = text.split("\n")
        return "\n".join(lines[(start or 1) - 1:end])

    async def write(self, path: str, text: str) -> None:
        self._put(path, text)

    async def delete(self, path: str) -> None:
        (self.root / path).unlink(missing_ok=True)

    async def search(self, pattern: str, glob: str | None = None, limit: int = 50) -> list[tuple[str, int, str]]:
        rx = re.compile(pattern)
        out = []
        for path, text in self.tree().items():
            if glob and not Path(path).match(glob):
                continue
            for n, line in enumerate(text.split("\n"), 1):
                if rx.search(line):
                    out.append((path, n, line))
                    if len(out) >= limit:
                        return out
        return out

    async def exec(self, cmd: str, timeout: int = 120) -> ExecResult:
        self.exec_log.append(cmd)
        argv = shlex.split(cmd)
        if argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(self.root),
               "PYTHONPATH": str(self.root)}
        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(*argv, cwd=self.root, env=env, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return ExecResult(124, "timeout", int((time.monotonic() - t0) * 1000))
        return ExecResult(proc.returncode or 0, out.decode(errors="replace")[-3000:], int((time.monotonic() - t0) * 1000))

    async def changed(self) -> dict[str, str | None]:
        now = self.tree()
        out: dict[str, str | None] = {p: t for p, t in now.items() if self.checkpoint.get(p) != t}
        for p in self.checkpoint:
            if p not in now:
                out[p] = None
        return out

    async def fork(self) -> "TmpWorkspace":
        return TmpWorkspace(self.tree(), checkpoint=self.checkpoint)

    async def release(self) -> None:
        self.released = True
        shutil.rmtree(self.root, ignore_errors=True)


class TmpFactory:
    async def open(self, files: dict[str, str], *, language_hint: str | None = None) -> TmpWorkspace:
        return TmpWorkspace(files)


# ---- fake verifiers ----------------------------------------------------------------------------------

@dataclass
class Criterion:
    id: str
    kind: str
    hard: bool
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Artifact:
    id: str
    kind: str
    label: str
    phase: str
    viewport: str | None
    mime: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


class ArtifactStore:
    def __init__(self) -> None:
        self._items: list[Artifact] = []

    def add(self, kind: str, label: str, phase: str, viewport: str | None, mime: str, data: bytes) -> Artifact:
        a = Artifact(f"a{len(self._items) + 1}", kind, label, phase, viewport, mime, data)
        self._items.append(a)
        return a

    def list(self) -> list[Artifact]:
        return list(self._items)

    def get(self, aid: str) -> Artifact | None:
        return next((a for a in self._items if a.id == aid), None)


@dataclass
class VerifyResult:
    criterion_id: str
    kind: str
    hard: bool
    status: str
    score: float | None
    detail: str
    artifacts: list[Artifact] = field(default_factory=list)


def build_repo_map(files: dict[str, str]) -> dict[str, Any]:
    return {"files": sorted(files)}


OK_LINE = re.compile(r"^\S+ \(([\w.]+)\)[^\n]*\.\.\. ok\s*$", re.M)


def _passing_ids(output: str) -> set[str]:
    return set(OK_LINE.findall(output))


async def _unittest(ws: Any) -> ExecResult:
    return await ws.exec("python -m unittest discover -s . -t . -p test*.py -v", 120)


def _public_api(files: dict[str, str]) -> dict[str, list[str]]:
    api: dict[str, list[str]] = {}
    for path, text in files.items():
        if path.endswith(".py") and "tests/" not in path:
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
                    args = [a.arg for a in node.args.args] if isinstance(node, ast.FunctionDef) else []
                    api[f"{path}:{node.name}"] = args
    return api


async def collect_baseline(ws: Any, repo_map: Any) -> dict[str, Any]:
    res = await _unittest(ws)
    files = {p: await ws.read(p) for p in await _py_files(ws)}
    return {"passing": sorted(_passing_ids(res.stdout_tail)), "api": _public_api(files)}


async def _py_files(ws: Any, base: str = ".") -> list[str]:
    out = []
    for name in await ws.list_dir(base):
        rel = name if base == "." else f"{base}/{name}"
        if name.endswith("/"):
            out += await _py_files(ws, rel.rstrip("/"))
        elif name.endswith(".py"):
            out.append(rel)
    return out


async def run_verifier(c: Criterion, ws: Any, baseline: Any, store: ArtifactStore) -> VerifyResult:
    k = c.kind

    def res(status: str, detail: str, score: float | None = None, arts: list[Artifact] | None = None) -> VerifyResult:
        return VerifyResult(c.id, c.kind, c.hard, status, score, detail, arts or [])

    if k == "build":
        out = await ws.exec("python -m compileall -q .", 60)
        return res("pass" if out.code == 0 else "fail", out.stdout_tail[-300:] or "compiles")
    if k in ("tests", "no_regression"):
        out = await _unittest(ws)
        now = _passing_ids(out.stdout_tail)
        if k == "tests":
            return res("pass" if out.code == 0 else "fail", out.stdout_tail[-300:])
        lost = sorted(set((baseline or {}).get("passing", [])) - now)
        art = store.add("log", "unittest output", "after", None, "text/plain", out.stdout_tail.encode())
        return res("fail" if lost else "pass", f"regressed: {lost}" if lost else f"{len(now)} tests still pass", arts=[art])
    if k in ("acceptance_tests", "characterization", "repro"):
        for p, t in (c.params.get("files") or {}).items():
            await ws.write(p, t)
        cmd = c.params.get("command") or " ".join(
            ["python", "-m", "unittest", *[p[:-3].replace("/", ".") for p in (c.params.get("files") or {})]])
        out = await ws.exec(cmd, 120)
        art = store.add("log", f"{k} output", "n/a", None, "text/plain", out.stdout_tail.encode())
        return res("pass" if out.code == 0 else "fail", out.stdout_tail[-400:], arts=[art])
    if k == "api_surface":
        files = {p: await ws.read(p) for p in await _py_files(ws)}
        before, after = (baseline or {}).get("api", {}), _public_api(files)
        gone = sorted(n for n in before if n not in after or after[n] != before[n])
        return res("fail" if gone else "pass", f"changed public API: {gone}" if gone else f"{len(before)} public symbols unchanged")
    if k in ("lint_typecheck", "complexity_metric", "policy", "security", "secrets"):
        return res("pass", f"{k}: fake verifier ok")
    if k == "command":
        out = await ws.exec(c.params["command"], 120)
        return res("pass" if out.code == 0 else "fail", out.stdout_tail[-300:])
    if k == "ui_build_console":
        return res("pass" if "index.html" in await ws.list_dir(".") else "fail", "index.html present")
    if k == "ui_overflow":
        css = await ws.read("styles.css")
        art = store.add("screenshot", "mobile 375", "after", "375", "image/png", b"\x89PNG fake")
        return res("fail" if "width: 2000px" in css else "pass", "fixed-width element" if "2000px" in css else "no overflow",
                   arts=[art])
    if k == "ui_axe":
        html = await ws.read("index.html")
        bad = len(re.findall(r"<img(?![^>]*alt=)", html))
        return res("fail" if bad else "pass", f"{bad} images without alt")
    if k == "ui_smoke":
        html = await ws.read("index.html")
        steps = c.params.get("steps") or []
        missing = [s["text"] for s in steps if s.get("action") == "expect_text" and s.get("text") not in html]
        return res("fail" if missing else "pass", f"missing: {missing}" if missing else "smoke steps ok")
    if k in ("advisory_vision", "advisory_rubric"):
        return res("advisory", "looks tidy (fake review)", 0.8)
    return res("skip", f"no verifier for {k}")


class FakeVerifiers:
    Criterion = Criterion


def make_deps() -> SwarmDeps:
    return SwarmDeps(workspace_factory=TmpFactory(), run_verifier=run_verifier, collect_baseline=collect_baseline,
                     build_repo_map=build_repo_map, criterion_cls=Criterion, artifact_store_cls=ArtifactStore)


# ---- fixture repos ----------------------------------------------------------------------------------

INVENTORY = {
    "inventory/__init__.py": "from inventory.stock import Inventory\n",
    "inventory/pricing.py": "UNIT_PRICES = {\"apple\": 2.0, \"pear\": 3.0}\n\n\ndef unit_price(sku):\n    return UNIT_PRICES[sku]\n",
    "inventory/stock.py": (
        "from inventory.pricing import unit_price\n\n\nclass Inventory:\n    def __init__(self):\n        self._items = {}\n\n"
        "    def add(self, sku, qty):\n        if qty <= 0:\n            raise ValueError('qty must be positive')\n"
        "        self._items[sku] = self._items.get(sku, 0) + qty\n\n"
        "    def remove(self, sku, qty):\n        if qty <= 0:\n            raise ValueError('qty must be positive')\n"
        "        if self._items.get(sku, 0) < qty:\n            raise ValueError('not enough stock')\n"
        "        self._items[sku] -= qty\n\n"
        "    def count(self, sku):\n        return self._items.get(sku, 0)\n\n"
        "    def value(self):\n        return sum(unit_price(s) * q for s, q in self._items.items())\n"),
    "tests/__init__.py": "",
    "tests/test_stock.py": (
        "import unittest\nfrom inventory import Inventory\n\n\nclass StockTests(unittest.TestCase):\n"
        "    def test_add_count(self):\n        i = Inventory()\n        i.add('apple', 3)\n        self.assertEqual(i.count('apple'), 3)\n\n"
        "    def test_value(self):\n        i = Inventory()\n        i.add('apple', 2)\n        self.assertEqual(i.value(), 4.0)\n"),
}

BULK_TEST = (
    "import unittest\nfrom inventory.pricing import line_price\nfrom inventory import Inventory\n\n\n"
    "class BulkTests(unittest.TestCase):\n"
    "    def test_small_orders_pay_full_price(self):\n        self.assertEqual(line_price('apple', 5), 10.0)\n\n"
    "    def test_bulk_discount(self):\n        self.assertEqual(line_price('apple', 20), 36.0)\n\n"
    "    def test_inventory_value_uses_bulk(self):\n        i = Inventory()\n        i.add('apple', 20)\n"
    "        self.assertEqual(i.value(), 36.0)\n")
PRICING_NEW = (INVENTORY["inventory/pricing.py"] +
               "\n\ndef line_price(sku, qty):\n    total = unit_price(sku) * qty\n    return total * 0.9 if qty >= 10 else total\n")
STOCK_NEW = INVENTORY["inventory/stock.py"].replace(
    "from inventory.pricing import unit_price", "from inventory.pricing import line_price").replace(
    "sum(unit_price(s) * q for s, q in self._items.items())", "sum(line_price(s, q) for s, q in self._items.items())")

CHAR_TEST = (
    "import unittest\nfrom inventory import Inventory\n\n\nclass Pinned(unittest.TestCase):\n"
    "    def test_add_remove_roundtrip(self):\n        i = Inventory()\n        i.add('pear', 4)\n        i.remove('pear', 1)\n"
    "        self.assertEqual(i.count('pear'), 3)\n\n"
    "    def test_errors(self):\n        i = Inventory()\n        with self.assertRaises(ValueError):\n            i.add('pear', 0)\n"
    "        with self.assertRaises(ValueError):\n            i.remove('pear', 1)\n")
STOCK_REFACTORED = INVENTORY["inventory/stock.py"].replace(
    "        if qty <= 0:\n            raise ValueError('qty must be positive')\n", "        _positive(qty)\n").replace(
    "class Inventory:", "def _positive(qty):\n    if qty <= 0:\n        raise ValueError('qty must be positive')\n\n\nclass Inventory:")

NOTES_UI = {
    "index.html": "<!doctype html><html><body><h1>Notes</h1><div class=\"box\">Hello</div><img src=\"a.png\"></body></html>\n",
    "styles.css": ".box { width: 2000px; }\n",
    "package.json": "{\"name\": \"notes\"}\n",
}


def feature_script() -> dict[str, Any]:
    return {
        "id": "inv-feature", "match": {"repo": "inventory-lib", "task_type": "feature", "keywords": ["bulk", "discount"]},
        "plan": {
            "task_type": "feature", "summary": "Add a 10% bulk discount for 10+ units and use it for inventory value.",
            "criteria": [{"id": "bulk_acceptance", "kind": "acceptance_tests", "hard": True, "user_stated": True,
                          "description": "line_price applies a 10% discount from 10 units"}],
            "units": [
                {"id": "pricing", "title": "Add line_price", "scope_files": ["inventory/pricing.py"], "variants": 1},
                {"id": "stock", "title": "Use bulk pricing in Inventory.value", "scope_files": ["inventory/stock.py"],
                 "depends_on": ["pricing"], "variants": 2}],
            "swarm": {"max_parallel": 3}},
        "spec": {"bulk_acceptance": {"files": {"tests/test_bulk.py": BULK_TEST}}},
        "workers": {
            "pricing": [{"variant": 0, "steps": [
                {"tool": "read_file", "args": {"path": "inventory/pricing.py"}},
                {"tool": "write_file", "args": {"path": "inventory/pricing.py", "content": PRICING_NEW}},
                {"tool": "run", "args": {"cmd": "python -m unittest tests.test_bulk"}}]}],
            "stock": [
                {"variant": 0, "steps": [
                    {"tool": "write_file", "args": {"path": "inventory/stock.py", "content": STOCK_NEW}}]},
                {"variant": 1, "steps": [
                    {"tool": "search", "args": {"regex": "def value"}, "delay_ms": 3000},
                    {"tool": "write_file", "args": {"path": "inventory/stock.py", "content": STOCK_NEW}}]}]},
    }


def refactor_script() -> dict[str, Any]:
    return {
        "id": "inv-refactor", "match": {"repo": "inventory-lib", "task_type": "refactor", "keywords": ["extract", "validation"]},
        "plan": {
            "task_type": "refactor", "summary": "Extract the quantity validation into one helper.",
            "criteria": [{"id": "pinned", "kind": "characterization", "hard": True, "user_stated": True,
                          "description": "add/remove behaviour is unchanged"}],
            "units": [{"id": "extract", "title": "Extract _positive", "scope_files": ["inventory/stock.py"]}]},
        "spec": {"pinned": {"files": {"tests/test_pinned.py": CHAR_TEST}}},
        "workers": {"extract": [{"variant": 0, "steps": [
            {"tool": "write_file", "args": {"path": "inventory/stock.py", "content": STOCK_REFACTORED}}]}]},
    }


def ui_script() -> dict[str, Any]:
    fixed_css = ".box { max-width: 100%; }\n"
    fixed_html = NOTES_UI["index.html"].replace("<img src=\"a.png\">", "<img src=\"a.png\" alt=\"logo\">")
    return {
        "id": "notes-ui", "match": {"repo": "react-notes", "task_type": "ui", "keywords": ["ui", "mobile"]},
        "plan": {
            "task_type": "ui", "summary": "Fix the overflow and accessibility of the notes page.",
            "criteria": [{"id": "look", "kind": "advisory_vision", "hard": False, "description": "looks better"}],
            "units": [{"id": "css", "title": "Responsive box", "scope_files": ["styles.css"]},
                      {"id": "html", "title": "Accessible images", "scope_files": ["index.html"]}],
            "swarm": {"max_parallel": 2}},
        "spec": {"ui_smoke": {"files": {}, "steps": [{"action": "expect_text", "text": "Notes"}]}},
        "workers": {
            "css": [{"variant": 0, "steps": [{"tool": "write_file", "args": {"path": "styles.css", "content": fixed_css}}]}],
            "html": [{"variant": 0, "steps": [{"tool": "write_file", "args": {"path": "index.html", "content": fixed_html}}]}]},
    }


def settings(tmp_path: Path | None = None, **over: Any) -> Settings:
    base = dict(shared_secret="s", mode="fake", fake_delay_scale=0.0, swarm_max_workers=4, swarm_max_tokens=400000,
                swarm_max_wall_s=60.0, swarm_worker_max_steps=12, swarm_max_rounds=3, swarm_max_units=8)
    if tmp_path:
        base["runs_dir"] = tmp_path
    base.update(over)
    return Settings(**base)


def make_ctx(files: dict[str, str], task: str, scripts: list[dict[str, Any]], tmp_path: Path, *, repo: str = "demo/inventory-lib",
             task_type: str = "auto", events: list[tuple[str, dict[str, Any]]] | None = None, answers: dict[str, str] | None = None,
             strict: list[str] | None = None, limits: dict[str, Any] | None = None, **over: Any) -> SwarmCtx:
    sdir = tmp_path / "scripts"
    sdir.mkdir(exist_ok=True)
    for s in scripts:
        (sdir / f"{s['id']}.json").write_text(json.dumps(s), encoding="utf-8")
    fake = FakeSwarm(sdir, delay_scale=1.0)
    log = events if events is not None else []

    async def emit(kind: str, data: dict[str, Any]) -> None:
        log.append((kind, data))

    return SwarmCtx(run_id="r1", task=task, full_name=repo, files=files, settings=settings(tmp_path, **over), emit=emit,
                    deps=make_deps(), llm_factory=fake.llm_factory(repo, task, task_type, answers or {}), mode="fake",
                    task_type=task_type, strict=strict or [], limits=limits or {}, answers=answers or {}, demo=True,
                    fake=fake, language="python", budget_tick_s=0.2)
