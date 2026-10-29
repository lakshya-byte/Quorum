"""Deterministic policy gate for AI-written candidates. No LLM, always fail-closed.

Rules (any violation blocks the candidate, which then scores 0):
- only the bug's target file may change;
- test files must be byte-identical to the originals (the harness always writes the original tests);
- the diff against the original source is at most `max_diff_lines` changed lines;
- the code must parse, and its AST must not use: os.system (and other os process calls), subprocess,
  socket, requests/httpx/urllib, eval, exec, __import__, ctypes, or open() on a path that is not a
  relative literal inside the working directory.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from app.scoring import changed_lines

DENIED_MODULES = {
    "subprocess", "socket", "requests", "httpx", "urllib", "urllib2", "urllib3", "ctypes",
    "http", "ftplib", "telnetlib", "smtplib", "multiprocessing", "pty", "shutil", "importlib",
}
DENIED_OS_ATTRS = {
    "system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp",
    "spawnvpe", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "fork", "forkpty", "kill", "remove", "unlink", "rmdir", "removedirs", "putenv",
}
DENIED_CALLS = {"eval", "exec", "__import__", "compile", "breakpoint"}
DENIED_NAMES = {"__builtins__", "__loader__"}
DEFAULT_MAX_DIFF = 60


@dataclass
class PolicyResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reasons": list(self.reasons)}


def _root(name: str | None) -> str:
    return (name or "").split(".", 1)[0]


def _safe_open_path(node: ast.Call) -> bool:
    """open() is allowed only with a relative literal path that stays inside the working dir."""
    target = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "file"), None)
    if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
        return False
    path = PurePosixPath(target.value.replace("\\", "/"))
    return bool(target.value) and not path.is_absolute() and ".." not in path.parts and not target.value.startswith("~")


def ast_violations(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"candidate does not parse: SyntaxError line {exc.lineno}: {exc.msg}"]

    found: list[str] = []
    os_aliases = {"os"}

    def add(msg: str, node: ast.AST) -> None:
        line = getattr(node, "lineno", "?")
        entry = f"line {line}: {msg}"
        if entry not in found:
            found.append(entry)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root(alias.name) in DENIED_MODULES:
                    add(f"imports denied module {alias.name}", node)
                if alias.name == "os" and alias.asname:
                    os_aliases.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if _root(mod) in DENIED_MODULES:
                add(f"imports from denied module {mod}", node)
            if mod == "os":
                for alias in node.names:
                    if alias.name in DENIED_OS_ATTRS or alias.name == "*":
                        add(f"imports os.{alias.name}", node)
            if mod == "builtins":
                add("imports from builtins", node)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in os_aliases and node.attr in DENIED_OS_ATTRS:
                add(f"uses os.{node.attr}", node)
            if node.attr in {"__subclasses__", "__globals__", "__code__", "__builtins__"}:
                add(f"uses dunder escape .{node.attr}", node)
        elif isinstance(node, ast.Name) and node.id in DENIED_NAMES:
            add(f"uses {node.id}", node)
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else None
            if name in DENIED_CALLS:
                add(f"calls {name}()", node)
            if name in {"getattr", "setattr", "delattr"} and node.args and isinstance(node.args[0], ast.Name) \
                    and node.args[0].id in os_aliases:
                add(f"uses {name}() on os", node)
            is_open = name == "open" or (
                isinstance(func, ast.Attribute) and func.attr == "open"
                and isinstance(func.value, ast.Name) and func.value.id in {"io", "os", "codecs"}
            )
            if is_open and not _safe_open_path(node):
                add("open() on a path outside the working directory (or not a literal)", node)
    return found


def check_candidate(
    bug: dict, changed_files: dict[str, str], *, max_diff_lines: int = DEFAULT_MAX_DIFF,
) -> PolicyResult:
    """`changed_files` maps filename -> new content for every file the candidate wants to write."""
    reasons: list[str] = []
    target = bug["target"]
    test_name = f"test_{target}"

    for name, text in changed_files.items():
        if name == test_name:
            if text != bug["tests"]:
                reasons.append(f"test file {name} modified (tests must stay byte-identical)")
        elif PurePosixPath(name).name.startswith("test_"):
            reasons.append(f"test file {name} added (only the target may change)")
        elif name != target:
            reasons.append(f"file {name} is outside the target {target}")

    code = changed_files.get(target)
    if code is None or not code.strip():
        reasons.append(f"no new content for the target {target}")
    else:
        diff = changed_lines(bug["buggy"], code)
        if diff > max_diff_lines:
            reasons.append(f"diff too large: {diff} changed lines > {max_diff_lines}")
        reasons.extend(ast_violations(code))
    return PolicyResult(ok=not reasons, reasons=reasons)
