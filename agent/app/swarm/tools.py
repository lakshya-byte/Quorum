"""Worker tools, executed against a sandbox Workspace (never on the agent host) and gated in code.

Every write passes `ToolBox.write_violation` (unit scope + path policy from app/policy.py + secrets + test immutability);
every `run` passes the allow-list `check_command`. A violation is returned to the model as a tool error; it never raises.
The final diff is re-filtered by `collect_changes`, so even side effects of `run` (formatters, code generators) can
never smuggle an out-of-scope or protected file into a unit result.
"""
from __future__ import annotations

import fnmatch
import re
import shlex
import time
from dataclasses import dataclass, field
from typing import Any

from app.policy import MAX_REPO_FILE_BYTES, ast_violations, path_violation
from app.repo_detect import is_test_path
from app.swarm.events import Redactor, looks_secret

READ_MAX_CHARS = 20_000
READ_MAX_LINES = 400
RUN_OUTPUT_TAIL = 3000
RUN_MAX_TIMEOUT = 300
MAX_NEW_FILES_PER_UNIT = 25
MAX_FILES_PER_RUN = 60
IGNORED_PARTS = {"__pycache__", ".pytest_cache", "node_modules", ".mypy_cache", ".ruff_cache", ".git", ".next",
                 "dist", "build", "coverage", ".cache", ".tox", ".venv", "venv", ".idea", ".vscode"}
IGNORED_SUFFIX = (".pyc", ".pyo", ".log", ".tmp", ".swp")

TOOL_NAMES = ("list_dir", "read_file", "search", "symbols", "write_file", "apply_patch", "run", "finish")


def _fn(name: str, description: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": required}}}


_S = {"type": "string"}
_I = {"type": "integer"}
TOOL_SPECS: list[dict[str, Any]] = [
    _fn("list_dir", "List a directory of the repository (relative path, default '.').", {"path": _S}, []),
    _fn("read_file", "Read a file (optionally lines start..end, 1-based inclusive).",
        {"path": _S, "start": _I, "end": _I}, ["path"]),
    _fn("search", "Regex search across the repository (optional glob filter, e.g. '*.py').",
        {"regex": _S, "glob": _S}, ["regex"]),
    _fn("symbols", "List the symbols (functions/classes) of a file, or find a symbol by name.",
        {"path_or_query": _S}, ["path_or_query"]),
    _fn("write_file", "Write the COMPLETE new content of a file inside your unit scope (or a new file).",
        {"path": _S, "content": _S}, ["path", "content"]),
    _fn("apply_patch", "Apply a unified diff to ONE file inside your unit scope.",
        {"path": _S, "unified_diff": _S}, ["path", "unified_diff"]),
    _fn("run", "Run an allow-listed project command (tests, build, lint, formatter, package install). "
               "One command only: no pipes, no &&, no redirects.", {"cmd": _S}, ["cmd"]),
    _fn("finish", "Finish the unit with a one-paragraph summary of what you changed.", {"summary": _S}, ["summary"]),
]


# ---- run() allow-list -----------------------------------------------------------------------

PY_MODULES = {"unittest", "pytest", "pip", "ruff", "mypy", "black", "flake8", "bandit", "compileall", "py_compile",
              "coverage", "pyflakes", "isort", "build"}
ANY_ARGS = {"pytest", "ruff", "mypy", "black", "flake8", "bandit", "eslint", "prettier", "tsc", "isort"}
NPM_SUB = {"test", "t", "run", "run-script", "ci", "install", "i", "build", "lint", "add"}
NPX_TOOLS = {"tsc", "eslint", "prettier", "vitest", "jest", "playwright", "vite", "stylelint"}
GO_SUB = {"test", "build", "vet", "fmt", "mod"}
CARGO_SUB = {"test", "build", "check", "clippy", "fmt"}
DENIED_FLAGS = {"-c", "--eval", "-e", "-p", "--print", "--index-url", "-i", "--extra-index-url", "--trusted-host",
                "--target", "--prefix", "--root", "--registry", "--userconfig", "--globalconfig", "--config"}
_META = re.compile(r"[|;&<>`$\n\r\\(){}]")
_SAFE_SCRIPT = re.compile(r"^[A-Za-z0-9_@+./-]+$")


def _bad_arg(tok: str) -> str | None:
    if tok.startswith("-"):
        flag = tok.split("=", 1)[0]
        if flag in DENIED_FLAGS:
            return f"flag {flag} is not allowed"
        val = tok.split("=", 1)[1] if "=" in tok else ""
        tok = val
        if not tok:
            return None
    if "://" in tok or tok.startswith("git+") or tok.startswith(("~", "/")) or re.match(r"^[A-Za-z]:", tok):
        return f"argument {tok[:40]!r}: absolute paths and URLs are not allowed"
    if ".." in tok.split("/"):
        return f"argument {tok[:40]!r}: path traversal"
    return None


def check_command(cmd: str) -> str | None:
    """Why `cmd` may not run (None = allowed). Pure function, deterministic, no I/O."""
    if not isinstance(cmd, str) or not cmd.strip():
        return "empty command"
    if len(cmd) > 400:
        return "command too long"
    if _META.search(cmd):
        return "shell metacharacters (| ; & < > ` $ \\ ( ) { } newline) are not allowed: run ONE plain command"
    try:
        toks = shlex.split(cmd, posix=True)
    except ValueError:
        return "unparseable command (unbalanced quotes)"
    if not toks:
        return "empty command"
    exe = toks[0]
    if "/" in exe or exe.startswith(("~", ".")):
        return "the executable must be a bare allow-listed name"
    for t in toks[1:]:
        bad = _bad_arg(t)
        if bad:
            return bad
    rest = toks[1:]
    if exe in ("python", "python3"):
        if not rest:
            return "interactive python is not allowed"
        if rest[0] == "-m":
            if len(rest) < 2 or rest[1] not in PY_MODULES:
                return f"python -m {rest[1] if len(rest) > 1 else ''}: module not in the allow-list"
            if rest[1] == "pip" and (len(rest) < 3 or rest[2] != "install"):
                return "only 'pip install' is allowed"
            return None
        if rest[0].startswith("-"):
            return f"python flag {rest[0]} is not allowed"
        if not (_SAFE_SCRIPT.match(rest[0]) and rest[0].endswith(".py")):
            return "python may only run a relative .py script or -m <allow-listed module>"
        return None
    if exe in ("pip", "pip3"):
        return None if rest and rest[0] == "install" else "only 'pip install' is allowed"
    if exe in ANY_ARGS:
        return None
    if exe in ("npm", "yarn", "pnpm"):
        if not rest or rest[0] not in NPM_SUB:
            return f"{exe} {rest[0] if rest else ''}: subcommand not in the allow-list ({', '.join(sorted(NPM_SUB))})"
        return None
    if exe == "npx":
        tools = [t for t in rest if not t.startswith("-")]
        return None if tools and tools[0] in NPX_TOOLS else "npx may only run: " + ", ".join(sorted(NPX_TOOLS))
    if exe == "node":
        if rest and not rest[0].startswith("-") and _SAFE_SCRIPT.match(rest[0]) and rest[0].endswith((".js", ".mjs", ".cjs")):
            return None
        return "node may only run a relative .js/.mjs/.cjs script"
    if exe == "go":
        return None if rest and rest[0] in GO_SUB else f"go subcommand must be one of {sorted(GO_SUB)}"
    if exe == "cargo":
        return None if rest and rest[0] in CARGO_SUB else f"cargo subcommand must be one of {sorted(CARGO_SUB)}"
    return f"{exe!r} is not an allow-listed project tool"


# ---- paths ----------------------------------------------------------------------------------

def read_violation(path: str) -> str | None:
    """Reading is looser than writing (CI config is fine to read) but never leaves the repository."""
    if not isinstance(path, str) or not path or len(path) > 300:
        return "empty or oversized path"
    if "\x00" in path or "\\" in path or path.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", path):
        return f"{path!r}: illegal or absolute path"
    parts = path.split("/")
    if ".." in parts:
        return f"{path}: path traversal"
    if ".git" in parts:
        return f"{path}: .git is off limits"
    return None


def norm(path: str) -> str:
    p = (path or ".").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/") or "."


def in_scope(path: str, scope: list[str]) -> bool:
    for s in scope:
        if s.endswith("/"):
            if path.startswith(s):
                return True
        elif any(c in s for c in "*?["):
            if fnmatch.fnmatch(path, s):
                return True
        elif path == s:
            return True
    return False


def scopes_overlap(a: list[str], b: list[str]) -> bool:
    """Conservative: exact, prefix or glob-vs-path overlap (used for the scheduler's file-scope locks)."""
    for x in a:
        for y in b:
            if x == y:
                return True
            xd, yd = x.endswith("/"), y.endswith("/")
            if xd and (y.startswith(x)):
                return True
            if yd and (x.startswith(y)):
                return True
            if any(c in x for c in "*?[") and fnmatch.fnmatch(y, x):
                return True
            if any(c in y for c in "*?[") and fnmatch.fnmatch(x, y):
                return True
    return False


def ignorable(path: str) -> bool:
    parts = path.split("/")
    return any(p in IGNORED_PARTS for p in parts[:-1]) or path.endswith(IGNORED_SUFFIX)


# ---- unified diff ---------------------------------------------------------------------------

class PatchError(ValueError):
    pass


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")


def apply_unified_diff(text: str, diff: str) -> str:
    """Apply a unified diff (single file). Line counts in hunk headers are ignored (models get them wrong);
    hunks are located by their context, searching outward from the stated line."""
    trailing = text.endswith("\n")
    lines = text.split("\n")
    if trailing:
        lines.pop()
    hunks: list[tuple[int, list[str], list[str]]] = []
    cur: tuple[int, list[str], list[str]] | None = None
    for raw in diff.split("\n"):
        m = _HUNK.match(raw)
        if m:
            cur = (int(m.group(1)), [], [])
            hunks.append(cur)
            continue
        if cur is None:
            continue  # headers (---/+++/diff) before the first hunk
        if raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            cur[2].append(raw[1:])
        elif raw.startswith("-"):
            cur[1].append(raw[1:])
        elif raw.startswith(" ") or raw == "":
            body = raw[1:] if raw.startswith(" ") else ""
            cur[1].append(body)
            cur[2].append(body)
    if not hunks:
        raise PatchError("no hunks found: use '@@ -a,b +c,d @@' hunks")
    offset = 0
    for n, (start, old, new) in enumerate(hunks, 1):
        while old and old[-1] == "" and new and new[-1] == "" and len(old) > 1 and old != [""]:
            old.pop()
            new.pop()  # blank context at the end of a diff body
        expected = max(0, start - 1 + offset)
        pos = _find(lines, old, expected)
        if pos is None:
            raise PatchError(f"hunk {n} does not apply near line {start}: context not found")
        lines[pos:pos + len(old)] = new
        offset += len(new) - len(old)
    return "\n".join(lines) + ("\n" if trailing or not lines else "")


def _find(lines: list[str], old: list[str], expected: int) -> int | None:
    if not old:
        return min(expected, len(lines))
    last = len(lines) - len(old)
    for dist in range(0, len(lines) + 1):
        for pos in ((expected - dist, expected + dist) if dist else (expected,)):
            if 0 <= pos <= last and lines[pos:pos + len(old)] == old:
                return pos
    stripped = [x.rstrip() for x in old]
    for pos in range(0, last + 1):
        if [x.rstrip() for x in lines[pos:pos + len(old)]] == stripped:
            return pos
    return None


# ---- symbols --------------------------------------------------------------------------------

_SYM = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:def|class|function|func|interface|type|enum|struct|fn)\s+"
    r"([A-Za-z_$][\w$]*)|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\(|function|[A-Za-z_$][\w$]*\s*=>)",
    re.MULTILINE)


def list_symbols(text: str, limit: int = 80) -> list[tuple[int, str]]:
    out = []
    for m in _SYM.finditer(text):
        name = m.group(1) or m.group(2)
        line = text.count("\n", 0, m.start()) + 1
        out.append((line, name))
        if len(out) >= limit:
            break
    return out


# ---- the toolbox ----------------------------------------------------------------------------

@dataclass
class ToolOutcome:
    ok: bool
    text: str
    target: str = ""
    note: str = ""
    finished: bool = False
    summary: str = ""


def _exec_fields(res: Any) -> tuple[int, str, int]:
    if isinstance(res, (tuple, list)):
        return int(res[0]), str(res[1]), int(res[2]) if len(res) > 2 else 0
    code = getattr(res, "code", getattr(res, "exit_code", 1))
    out = getattr(res, "stdout_tail", getattr(res, "output", ""))
    return int(code), str(out), int(getattr(res, "duration_ms", 0) or 0)


@dataclass
class ToolBox:
    ws: Any
    original: dict[str, str]  # the unit's starting state (path -> text) for existing-file decisions
    scope: list[str]
    frozen: set[str] = field(default_factory=set)  # verifier/spec files: never writable
    allow_tests: bool = False  # task_type == "tests"
    redactor: Redactor = field(default_factory=Redactor)
    isolation: str = "local"
    max_new_files: int = MAX_NEW_FILES_PER_UNIT
    written: set[str] = field(default_factory=set)
    new_files: set[str] = field(default_factory=set)

    # -- policy
    def write_violation(self, path: str, text: Any) -> str | None:
        bad = path_violation(path) if isinstance(path, str) else "path must be a string"
        if bad:
            return bad
        if not isinstance(text, str):
            return "content must be a string"
        if path in self.frozen:
            return f"{path}: protected verification file (acceptance/characterization/smoke checks are immutable)"
        if is_test_path(path) and not self.allow_tests:
            return f"{path}: test files and test config are immutable for this task type"
        exists = path in self.original
        if exists and not in_scope(path, self.scope):
            return f"{path}: outside this unit's scope {self.scope[:6]}"
        if not exists and path not in self.new_files and len(self.new_files) >= self.max_new_files:
            return f"too many new files (max {self.max_new_files} per unit)"
        if len(text.encode("utf-8", errors="replace")) > MAX_REPO_FILE_BYTES:
            return f"{path}: file too large (> {MAX_REPO_FILE_BYTES} bytes)"
        if exists and not text.strip():
            return f"{path}: refusing to blank an existing file"
        hits = looks_secret(text)
        if hits:
            return f"{path}: secret-looking string in content ({hits[0]}); never write credentials"
        if self.isolation == "local" and path.endswith(".py"):
            viol = ast_violations(text)
            if viol:
                return f"{path}: not allowed when running on the local sandbox: {viol[0]}"
        return None

    # -- dispatch
    async def call(self, name: str, args: Any) -> ToolOutcome:
        t0 = time.monotonic()
        if not isinstance(args, dict):
            return ToolOutcome(False, "arguments must be an object", note="bad args")
        try:
            handler = getattr(self, f"_t_{name}", None) if name in TOOL_NAMES else None
            if handler is None:
                return ToolOutcome(False, f"unknown tool {name!r}; available: {', '.join(TOOL_NAMES)}", note="unknown tool")
            out: ToolOutcome = await handler(args)
        except Exception as exc:  # a tool never crashes the worker loop
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            out = ToolOutcome(False, f"tool error: {type(exc).__name__}: {str(exc)[:200]}", note=type(exc).__name__)
        out.text = self.redactor.text(out.text)
        out.note = self.redactor.text(out.note)
        return out

    async def _t_list_dir(self, a: dict[str, Any]) -> ToolOutcome:
        path = norm(str(a.get("path") or "."))
        bad = read_violation(path) if path != "." else None
        if bad:
            return ToolOutcome(False, bad, path, "denied")
        names = await self.ws.list_dir(path)
        shown = names[:200]
        more = f"\n... {len(names) - 200} more" if len(names) > 200 else ""
        return ToolOutcome(True, "\n".join(shown) + more or "(empty)", path, f"{len(names)} entries")

    async def _t_read_file(self, a: dict[str, Any]) -> ToolOutcome:
        path = norm(str(a.get("path", "")))
        bad = read_violation(path)
        if bad:
            return ToolOutcome(False, bad, path, "denied")
        start, end = _int(a.get("start")), _int(a.get("end"))
        text = await self.ws.read(path, start, end)
        lines = text.split("\n")
        note = f"{len(lines)} lines"
        if len(lines) > READ_MAX_LINES:
            text = "\n".join(lines[:READ_MAX_LINES]) + f"\n... truncated: {len(lines) - READ_MAX_LINES} more lines (use start/end)"
        if len(text) > READ_MAX_CHARS:
            text = text[:READ_MAX_CHARS] + "\n... truncated (use start/end)"
        return ToolOutcome(True, text, path, note)

    async def _t_search(self, a: dict[str, Any]) -> ToolOutcome:
        pattern = str(a.get("regex", ""))
        if not pattern or len(pattern) > 200:
            return ToolOutcome(False, "regex must be 1-200 chars", "", "bad regex")
        try:
            re.compile(pattern)
        except re.error as exc:
            return ToolOutcome(False, f"invalid regex: {exc}", "", "bad regex")
        glob = a.get("glob")
        hits = await self.ws.search(pattern, str(glob) if glob else None, 50)
        body = "\n".join(f"{p}:{n}: {line[:200]}" for p, n, line in hits) or "(no matches)"
        return ToolOutcome(True, body, pattern[:60], f"{len(hits)} hits")

    async def _t_symbols(self, a: dict[str, Any]) -> ToolOutcome:
        q = str(a.get("path_or_query", "")).strip()
        if not q:
            return ToolOutcome(False, "give a file path or a symbol name", "", "bad args")
        if "/" in q or "." in q:
            if read_violation(q):
                return ToolOutcome(False, read_violation(q) or "", q, "denied")
            try:
                text = await self.ws.read(norm(q))
            except Exception:
                text = ""
            if text:
                syms = list_symbols(text)
                return ToolOutcome(True, "\n".join(f"{n}: {s}" for n, s in syms) or "(no symbols found)", q,
                                   f"{len(syms)} symbols")
        pattern = r"\b(?:def|class|function|func|interface|type|enum|const|let|var|fn)\s+\w*" + re.escape(q) + r"\w*"
        hits = await self.ws.search(pattern, None, 30)
        return ToolOutcome(True, "\n".join(f"{p}:{n}: {line.strip()[:160]}" for p, n, line in hits) or "(none)",
                           q[:60], f"{len(hits)} hits")

    async def _t_write_file(self, a: dict[str, Any]) -> ToolOutcome:
        path = norm(str(a.get("path", "")))
        text = a.get("content")
        bad = self.write_violation(path, text)
        if bad:
            return ToolOutcome(False, f"POLICY: {bad}", path, "policy denied")
        await self._commit(path, str(text))
        return ToolOutcome(True, f"wrote {path} ({len(str(text))} chars)", path, "ok")

    async def _t_apply_patch(self, a: dict[str, Any]) -> ToolOutcome:
        path = norm(str(a.get("path", "")))
        diff = a.get("unified_diff", a.get("diff"))
        if not isinstance(diff, str) or not diff.strip():
            return ToolOutcome(False, "unified_diff must be a non-empty string", path, "bad args")
        pre = path_violation(path)
        if pre:
            return ToolOutcome(False, f"POLICY: {pre}", path, "policy denied")
        try:
            current = await self.ws.read(path)
        except Exception:
            current = ""
        try:
            new = apply_unified_diff(current, diff)
        except PatchError as exc:
            return ToolOutcome(False, f"patch failed: {exc}", path, "patch failed")
        bad = self.write_violation(path, new)
        if bad:
            return ToolOutcome(False, f"POLICY: {bad}", path, "policy denied")
        await self._commit(path, new)
        return ToolOutcome(True, f"patched {path}", path, "ok")

    async def _commit(self, path: str, text: str) -> None:
        await self.ws.write(path, text)
        self.written.add(path)
        if path not in self.original:
            self.new_files.add(path)

    async def _t_run(self, a: dict[str, Any]) -> ToolOutcome:
        cmd = str(a.get("cmd", "")).strip()
        bad = check_command(cmd)
        if bad:
            return ToolOutcome(False, f"DENIED: {bad}", cmd[:80], "command denied")
        timeout = max(1, min(_int(a.get("timeout")) or 120, RUN_MAX_TIMEOUT))
        res = await self.ws.exec(cmd, timeout)
        code, out, ms = _exec_fields(res)
        tail = out[-RUN_OUTPUT_TAIL:]
        return ToolOutcome(code == 0, f"exit code {code}\n{tail}", cmd[:80], f"exit {code} in {ms}ms")

    async def _t_finish(self, a: dict[str, Any]) -> ToolOutcome:
        summary = " ".join(str(a.get("summary", "")).split())[:600]
        return ToolOutcome(True, "finished", "", "finish", finished=True, summary=summary or "done")

    # -- results
    async def collect_changes(self) -> tuple[dict[str, str | None], list[str]]:
        """The unit's diff vs its starting state, re-filtered through the same policy (covers side effects of run())."""
        changed = await self.ws.changed()
        keep: dict[str, str | None] = {}
        dropped: list[str] = []
        new_count = 0
        for path, text in sorted(changed.items()):
            if ignorable(path):
                continue
            if text is not None and self.original.get(path) == text:
                continue
            if path_violation(path) or path in self.frozen or (is_test_path(path) and not self.allow_tests):
                dropped.append(path)
                continue
            exists = path in self.original
            if exists and path not in self.written and not in_scope(path, self.scope):
                dropped.append(path)
                continue
            if exists and not in_scope(path, self.scope):
                dropped.append(path)
                continue
            if text is None:
                if exists and in_scope(path, self.scope):
                    keep[path] = None
                else:
                    dropped.append(path)
                continue
            if not exists:
                new_count += 1
                if new_count > self.max_new_files:
                    dropped.append(path)
                    continue
            if len(text.encode("utf-8", errors="replace")) > MAX_REPO_FILE_BYTES or looks_secret(text):
                dropped.append(path)
                continue
            keep[path] = text
        return keep, dropped


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
