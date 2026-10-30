"""Sandbox workspaces for the swarm: every tool call of a worker/verifier runs against a `Workspace`, never on
the agent host. Two implementations of the contract-v3 section 6 protocol:

- `LocalWorkspace`  : temp dir + isolated subprocesses (minimal env, no secrets, process-group kill, output caps).
                      isolation="local". Refuses non-demo repos unless ALLOW_LOCAL_REPO_EXEC=1.
- `NebiusWorkspace` : Contree (Nebius Sandboxes). One checkpoint image per repo, one disposable instance per exec.
                      isolation="nebius".

What is verified and what is not (honest):
- LocalWorkspace is exercised by the test-suite (real subprocesses, real npm/vitest/vite in the demo repos).
- NebiusWorkspace is tested against a MOCKED contree-sdk only. Unverified live: forking/exec of non-python images
  (NODE_IMAGE / UI_IMAGE / GO_IMAGE pulls), install persistence across execs (we run install steps with
  disposable=False and continue from the resulting image), chromium in a sandbox image, and large (3000 file)
  uploads. Files created by an exec (build output) are NOT read back from a disposable instance; only `write()`
  calls are tracked, so `changed()` reports the files the worker wrote, not build artifacts.
- Networking: contree-sdk 0.3.6 has no switch to disable instance networking, so sandboxes have the platform
  default network. Local mode passes proxy settings only to package-install steps and never any secrets.

Policy hooks (set by the swarm scheduler): `ws.scope` (iterable of paths/globs the unit may edit; NEW files are
always allowed when the path is safe), `ws.allow_tests` (default False: existing test files are immutable) and
`ws.policy` (callable `(path, text|None) -> reason|None` for extra rules). Violations raise `PolicyError`.
"""
from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable, Iterable, Protocol, runtime_checkable

from app.config import CACHE_DIR
from app.policy import path_violation
from app.repo_detect import is_test_path
from app.swarm.exec_policy import ExecDenied, Step, is_install, parse_command

MAX_FILE_WRITE_BYTES = 1_000_000
MAX_FILES = int(os.environ.get("WORKSPACE_MAX_FILES", "3000") or 3000)
MAX_TOTAL_BYTES = int(os.environ.get("WORKSPACE_MAX_BYTES", str(60 * 1024 * 1024)) or 60 * 1024 * 1024)
OUTPUT_TAIL_CHARS = 20_000
READ_CAP_CHARS = 60_000
EXEC_TIMEOUT_MAX = 900
TIMEOUT_EXIT = 124
DENIED_EXIT = 126

IGNORE_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "target", "__pycache__", ".venv", "venv", "env", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode", "site-packages", ".next", "coverage",
    ".vite", ".cache", ".parcel-cache", ".turbo", "test-results", "playwright-report", ".patchloop",
}
IGNORE_SUFFIX = (".pyc", ".pyo", ".tsbuildinfo", ".log", ".DS_Store")
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy", "SSL_CERT_FILE",
              "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "GOPROXY", "GOFLAGS", "GONOSUMDB",
              "GONOSUMCHECK", "GOSUMDB")


class PolicyError(Exception):
    """A write/delete outside what the unit or policy allows."""


class WorkspaceError(Exception):
    """Operational failure (refused repo, caps, missing sandbox backend)."""


@dataclass
class ExecResult:
    code: int
    stdout_tail: str
    duration_ms: int

    @property
    def stdout(self) -> str:
        return self.stdout_tail

    @property
    def output(self) -> str:
        return self.stdout_tail

    @property
    def ok(self) -> bool:
        return self.code == 0

    def __iter__(self):  # tuple-unpack as (code, stdout_tail, duration_ms)
        yield self.code
        yield self.stdout_tail
        yield self.duration_ms


@runtime_checkable
class Workspace(Protocol):
    isolation: str

    async def list_dir(self, path: str = ".") -> list[str]: ...
    async def read(self, path: str, start: int | None = None, end: int | None = None) -> str: ...
    async def write(self, path: str, text: str) -> None: ...
    async def search(self, pattern: str, glob: str | None = None, limit: int = 50) -> list[tuple[str, int, str]]: ...
    async def exec(self, cmd: str, timeout: int = 120) -> ExecResult: ...
    async def changed(self) -> dict[str, str | None]: ...
    async def fork(self) -> "Workspace": ...
    async def release(self) -> None: ...


class WorkspaceFactory(Protocol):
    async def open(self, files: dict[str, str], *, language_hint: str | None) -> Workspace: ...


# ---- shared helpers ---------------------------------------------------------------------------------------

def norm_path(path: str) -> str:
    """Repo-relative POSIX path; PolicyError for anything that could escape or is malformed."""
    if not isinstance(path, str) or not path or len(path) > 300:
        raise PolicyError("empty or oversized path")
    if path in (".", "./"):
        return "."
    bad = path_violation(path.removeprefix("./"))
    if bad:
        raise PolicyError(bad)
    return path.removeprefix("./")


def tail(text: str, cap: int = OUTPUT_TAIL_CHARS) -> str:
    return text if len(text) <= cap else "...[truncated]...\n" + text[-cap:]


def slice_lines(text: str, start: int | None, end: int | None) -> str:
    if start is None and end is None:
        out = text
    else:
        lines = text.splitlines(keepends=True)
        s = max((start or 1) - 1, 0)
        out = "".join(lines[s:end if end is not None else len(lines)])
    return out if len(out) <= READ_CAP_CHARS else out[:READ_CAP_CHARS] + "\n...[truncated: read a smaller range]"


def glob_match(path: str, pattern: str) -> bool:
    if fnmatch.fnmatch(path, pattern) or PurePosixPath(path).match(pattern):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
        return True
    return pattern.endswith("/") and path.startswith(pattern)


def _ignored(rel: str, orig_dirs: set[str]) -> bool:
    parts = rel.split("/")
    for i, part in enumerate(parts[:-1]):
        if part in IGNORE_DIRS and "/".join(parts[: i + 1]) not in orig_dirs:
            return True
    return rel.endswith(IGNORE_SUFFIX) or parts[-1] == ".DS_Store"


def _dirs_of(paths: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for p in paths:
        parts = p.split("/")[:-1]
        for i in range(len(parts)):
            out.add("/".join(parts[: i + 1]))
    return out


def sanitized_env(home: str, root: str, *, with_proxy: bool, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Minimal environment: no API keys, tokens or the agent's own settings ever reach a command."""
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    py_bin = str(Path(sys.executable).parent)
    if py_bin not in path.split(os.pathsep):
        path = py_bin + os.pathsep + path
    env = {
        "PATH": path, "HOME": home, "CI": "1", "LANG": "C.UTF-8", "TERM": "dumb", "TMPDIR": home,
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": root, "PYTHONUNBUFFERED": "1",
        "npm_config_cache": str(CACHE_DIR / "npm-cache"), "npm_config_update_notifier": "false",
        "npm_config_fund": "false", "npm_config_audit": "false", "npm_config_progress": "false",
        "NO_COLOR": "1",
        "GOCACHE": str(CACHE_DIR / "go-build"), "GOPATH": str(CACHE_DIR / "gopath"),
        "CARGO_HOME": str(CACHE_DIR / "cargo"), "CARGO_TARGET_DIR": os.path.join(home, "cargo-target"),
    }
    for key in ("PLAYWRIGHT_BROWSERS_PATH", "JAVA_HOME", "GOROOT", "RUSTUP_HOME"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    if with_proxy:
        for key in PROXY_VARS:
            if os.environ.get(key):
                env[key] = os.environ[key]
    env.update(extra or {})
    return env


# ---- demo detection ---------------------------------------------------------------------------------------

_DEMO_CACHE: list[dict[str, str]] | None = None


def _demo_trees() -> list[dict[str, str]]:
    global _DEMO_CACHE
    if _DEMO_CACHE is None:
        from app import repo_loader

        trees: list[dict[str, str]] = []
        for base in sorted(p for p in repo_loader.DEMO_DIR.iterdir() if (p / "repo").is_dir()):
            trees.append(repo_loader._read_tree(base / "repo"))
        _DEMO_CACHE = trees
    return _DEMO_CACHE


def is_demo_files(files: dict[str, str]) -> bool:
    """True when `files` is a bundled demo repo (every file of some demo repo present and byte-identical)."""
    for tree in _demo_trees():
        if tree and all(files.get(p) == t for p, t in tree.items()):
            return True
    return False


# ---- base class with the policy-checked write path --------------------------------------------------------

class _BaseWorkspace:
    isolation = "local"

    def __init__(self, originals: dict[str, str]) -> None:
        self._orig = originals
        self.scope: Iterable[str] | None = None
        self.allow_tests: bool = False
        self.policy: Callable[[str, str | None], str | None] | None = None
        self.max_files = MAX_FILES
        self.max_total_bytes = MAX_TOTAL_BYTES
        self.max_file_bytes = MAX_FILE_WRITE_BYTES
        self.writes = 0

    # hooks inherited by forks
    def _copy_hooks(self, other: "_BaseWorkspace") -> None:
        other.scope = list(self.scope) if self.scope is not None else None
        other.allow_tests, other.policy = self.allow_tests, self.policy
        other.max_files, other.max_total_bytes, other.max_file_bytes = self.max_files, self.max_total_bytes, \
            self.max_file_bytes

    def _in_scope(self, path: str) -> bool:
        if self.scope is None:
            return True
        return any(path == s or glob_match(path, s) for s in self.scope)

    def _check_mutation(self, path: str, text: str | None) -> str:
        rel = norm_path(path)
        if rel == ".":
            raise PolicyError("cannot write a directory")
        parts = rel.split("/")
        if any(p in IGNORE_DIRS and "/".join(parts[: i + 1]) not in _dirs_of(self._orig)
               for i, p in enumerate(parts[:-1])):
            raise PolicyError(f"{rel}: generated/vendor directories are not writable")
        existing = rel in self._orig
        if existing and not self._in_scope(rel):
            raise PolicyError(f"{rel}: outside the unit scope (new files are allowed, existing files are not)")
        if existing and is_test_path(rel) and not self.allow_tests:
            raise PolicyError(f"{rel}: existing test files are immutable for this task type")
        if text is not None:
            size = len(text.encode("utf-8", errors="replace"))
            if size > self.max_file_bytes:
                raise PolicyError(f"{rel}: {size} bytes exceeds the {self.max_file_bytes} byte file limit")
        if self.policy is not None:
            reason = self.policy(rel, text)
            if reason:
                raise PolicyError(f"{rel}: {reason}")
        return rel

    async def put_trusted(self, path: str, text: str) -> None:
        """Harness-only write (verifiers installing spec tests): path/size/cap rules apply, scope/test rules do not."""
        rel = norm_path(path)
        if rel == ".":
            raise PolicyError("cannot write a directory")
        if len(text.encode("utf-8", errors="replace")) > self.max_file_bytes:
            raise PolicyError(f"{rel}: exceeds the file size limit")
        await self._store(rel, text)

    def _check_caps(self, rel: str, text: str, current: dict[str, int]) -> None:
        sizes = dict(current)
        sizes[rel] = len(text.encode("utf-8", errors="replace"))
        if len(sizes) > self.max_files:
            raise PolicyError(f"workspace file cap reached ({self.max_files})")
        if sum(sizes.values()) > self.max_total_bytes:
            raise PolicyError(f"workspace size cap reached ({self.max_total_bytes} bytes)")

    @staticmethod
    def _search_text(lines_by_path: Iterable[tuple[str, str]], pattern: str, glob: str | None, limit: int):
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from None
        hits: list[tuple[str, int, str]] = []
        for path, text in lines_by_path:
            if glob and not glob_match(path, glob):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append((path, n, line[:240]))
                    if len(hits) >= limit:
                        return hits
        return hits


# ---- local ------------------------------------------------------------------------------------------------

class LocalWorkspace(_BaseWorkspace):
    isolation = "local"

    def __init__(self, parent: str, files: dict[str, str], originals: dict[str, str], slots: asyncio.Semaphore,
                 language_hint: str | None = None) -> None:
        super().__init__(originals)
        self._parent = parent
        self.root = os.path.join(parent, "ws")
        self._home = os.path.join(parent, "home")
        self._slots = slots
        self.language_hint = language_hint
        self._sizes: dict[str, int] = {p: len(t.encode("utf-8", errors="replace")) for p, t in files.items()}
        self._released = False

    # -- construction
    @classmethod
    def create(cls, files: dict[str, str], slots: asyncio.Semaphore, language_hint: str | None) -> "LocalWorkspace":
        if len(files) > MAX_FILES:
            raise WorkspaceError(f"too many files: {len(files)} > {MAX_FILES}")
        if sum(len(t) for t in files.values()) > MAX_TOTAL_BYTES:
            raise WorkspaceError("repository too large for a workspace")
        parent = tempfile.mkdtemp(prefix="patchloop-ws-")
        os.makedirs(os.path.join(parent, "ws"))
        os.makedirs(os.path.join(parent, "home"))
        from app.sandbox import write_tree

        write_tree(os.path.join(parent, "ws"), files)
        return cls(parent, files, dict(files), slots, language_hint)

    def _abs(self, rel: str) -> str:
        full = os.path.realpath(os.path.join(self.root, rel))
        root = os.path.realpath(self.root)
        if full != root and not full.startswith(root + os.sep):
            raise PolicyError(f"{rel}: resolves outside the workspace")
        return full

    # -- file tools
    async def list_dir(self, path: str = ".") -> list[str]:
        rel = norm_path(path)
        full = self._abs(rel)
        if not os.path.isdir(full):
            raise FileNotFoundError(f"not a directory: {rel}")
        orig_dirs = _dirs_of(self._orig)
        out = []
        for name in sorted(os.listdir(full)):
            child = name if rel == "." else f"{rel}/{name}"
            if name in IGNORE_DIRS and child not in orig_dirs:
                continue
            out.append(child + ("/" if os.path.isdir(os.path.join(full, name)) else ""))
        return out[:500]

    async def read(self, path: str, start: int | None = None, end: int | None = None) -> str:
        rel = norm_path(path)
        full = self._abs(rel)
        if not os.path.isfile(full):
            raise FileNotFoundError(f"no such file: {rel}")
        if os.path.getsize(full) > 5_000_000:
            raise WorkspaceError(f"{rel}: file too large to read")
        with open(full, "rb") as fh:
            raw = fh.read()
        if b"\x00" in raw[:8192]:
            raise WorkspaceError(f"{rel}: binary file")
        return slice_lines(raw.decode("utf-8", errors="replace"), start, end)

    async def write(self, path: str, text: str) -> None:
        rel = self._check_mutation(path, text)
        await self._store(rel, text)  # os.replace (not truncate): hard-linked forks never see the change
        self.writes += 1

    async def _store(self, rel: str, text: str) -> None:
        self._check_caps(rel, text, self._sizes)
        full = self._abs(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        tmp = full + ".pl-tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, full)
        self._sizes[rel] = len(text.encode("utf-8", errors="replace"))

    async def exists(self, path: str) -> bool:
        return os.path.exists(self._abs(norm_path(path)))

    async def read_tree_bytes(self, rel_dir: str, max_bytes: int = 8_000_000) -> dict[str, bytes]:
        """Binary-safe read of a (build output) directory, capped; used to serve/screenshot built web apps."""
        base = self._abs(norm_path(rel_dir))
        out: dict[str, bytes] = {}
        total = 0
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    continue
                total += os.path.getsize(full)
                if total > max_bytes:
                    raise WorkspaceError("build output too large")
                with open(full, "rb") as fh:
                    out[os.path.relpath(full, base).replace(os.sep, "/")] = fh.read()
        return out

    async def delete(self, path: str) -> None:
        rel = self._check_mutation(path, None)
        full = self._abs(rel)
        if not os.path.isfile(full):
            raise FileNotFoundError(f"no such file: {rel}")
        os.remove(full)
        self._sizes.pop(rel, None)
        self.writes += 1

    def _iter_text(self):
        orig_dirs = _dirs_of(self._orig)
        base = os.path.realpath(self.root)
        for dirpath, dirnames, filenames in os.walk(base):
            rel_dir = os.path.relpath(dirpath, base).replace(os.sep, "/")
            rel_dir = "" if rel_dir == "." else rel_dir
            dirnames[:] = sorted(d for d in dirnames
                                 if not (d in IGNORE_DIRS and (f"{rel_dir}/{d}" if rel_dir else d) not in orig_dirs))
            for name in sorted(filenames):
                rel = f"{rel_dir}/{name}" if rel_dir else name
                if _ignored(rel, orig_dirs) or os.path.islink(os.path.join(dirpath, name)):
                    continue
                yield rel, os.path.join(dirpath, name)

    @staticmethod
    def _read_text(full: str) -> str | None:
        try:
            if os.path.getsize(full) > 2_000_000:
                return None
            with open(full, "rb") as fh:
                raw = fh.read()
            if b"\x00" in raw[:8192]:
                return None
            return raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    async def search(self, pattern: str, glob: str | None = None, limit: int = 50) -> list[tuple[str, int, str]]:
        def gen():
            for rel, full in self._iter_text():
                text = self._read_text(full)
                if text is not None:
                    yield rel, text
        return await asyncio.to_thread(self._search_text, gen(), pattern, glob, min(max(limit, 1), 500))

    async def snapshot(self) -> dict[str, str]:
        """Current text of every tracked/non-ignored file (verifiers use this for scans)."""
        def work():
            out = {}
            for rel, full in self._iter_text():
                text = self._read_text(full)
                if text is not None:
                    out[rel] = text
            return out
        return await asyncio.to_thread(work)

    async def changed(self) -> dict[str, str | None]:
        current = await self.snapshot()
        diff: dict[str, str | None] = {p: t for p, t in current.items() if self._orig.get(p) != t}
        for p in self._orig:
            if p not in current and not os.path.exists(os.path.join(self.root, p)):
                diff[p] = None
        return diff

    # -- exec
    async def exec(self, cmd: str, timeout: int = 120) -> ExecResult:
        t0 = time.monotonic()
        try:
            steps = parse_command(cmd, self.isolation)
        except ExecDenied as exc:
            return ExecResult(DENIED_EXIT, f"COMMAND_DENIED: {exc}", 0)
        timeout = max(1, min(int(timeout), EXEC_TIMEOUT_MAX))
        out_parts: list[str] = []
        code = 0
        async with self._slots:
            for step in steps:
                left = timeout - (time.monotonic() - t0)
                if left <= 0:
                    code = TIMEOUT_EXIT
                    out_parts.append("TIMEOUT")
                    break
                code, out = await self._run_step(step, left)
                out_parts.append(out)
                if code != 0:
                    break
        return ExecResult(code, tail("".join(out_parts)), int((time.monotonic() - t0) * 1000))

    async def _run_step(self, step: Step, timeout: float) -> tuple[int, str]:
        cwd = self._abs(step.cwd if step.cwd != "." else ".")
        if not os.path.isdir(cwd):
            return 1, f"SANDBOX_ERROR: no such directory {step.cwd}\n"
        argv = list(step.argv)
        if argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        env = sanitized_env(self._home, self.root, with_proxy=is_install(step))
        os.makedirs(env["npm_config_cache"], exist_ok=True)
        # bytecode caches live outside the tree and die with the step: a stale .pyc (same size + mtime second)
        # must never mask an edit, and compileall must not leave files behind in forks
        pyc = tempfile.mkdtemp(prefix="pyc-", dir=self._parent)
        env["PYTHONPYCACHEPREFIX"] = pyc
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, start_new_session=True,
            )
        except FileNotFoundError:
            return 127, f"SANDBOX_ERROR: command not found: {argv[0]}\n"
        except OSError as exc:
            return 126, f"SANDBOX_ERROR: {type(exc).__name__}: {exc}\n"

        def kill_group() -> None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)

        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            kill_group()
            with contextlib.suppress(Exception):
                await proc.wait()
            return TIMEOUT_EXIT, "TIMEOUT\n"
        except asyncio.CancelledError:
            kill_group()
            raise
        finally:
            shutil.rmtree(pyc, ignore_errors=True)
        kill_group()  # reap stray children (dev servers, watchers) that outlived the command
        return proc.returncode or 0, out.decode("utf-8", errors="replace")

    # -- lifecycle
    async def fork(self) -> "LocalWorkspace":
        parent = tempfile.mkdtemp(prefix="patchloop-ws-")
        os.makedirs(os.path.join(parent, "home"))
        dst = os.path.join(parent, "ws")

        def link_heavy(src: str, d: str) -> None:
            try:
                os.link(src, d)  # node_modules & friends are never modified in place by the toolchain
            except OSError:
                shutil.copy2(src, d)

        def copy():
            heavy = {"node_modules", ".venv", "venv", "site-packages"}
            for dirpath, dirnames, filenames in os.walk(self.root):
                rel = os.path.relpath(dirpath, self.root)
                target = dst if rel == "." else os.path.join(dst, rel)
                os.makedirs(target, exist_ok=True)
                in_heavy = any(part in heavy for part in rel.split(os.sep))
                for name in filenames:
                    s, d = os.path.join(dirpath, name), os.path.join(target, name)
                    if os.path.islink(s):
                        os.symlink(os.readlink(s), d)
                    elif in_heavy:
                        link_heavy(s, d)
                    else:
                        shutil.copy2(s, d)
                for name in dirnames:
                    if os.path.islink(os.path.join(dirpath, name)):
                        os.symlink(os.readlink(os.path.join(dirpath, name)), os.path.join(target, name))
                dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]

        await asyncio.to_thread(copy)
        other = LocalWorkspace(parent, {}, self._orig, self._slots, self.language_hint)
        other._sizes = dict(self._sizes)
        self._copy_hooks(other)
        return other

    async def release(self) -> None:
        if not self._released:
            self._released = True
            shutil.rmtree(self._parent, ignore_errors=True)


class LocalWorkspaceFactory:
    """One workspace per repo; forks are cheap copies of the (possibly installed) tree."""

    def __init__(self, *, demo: bool | None = None, allow_non_demo: bool | None = None, concurrency: int = 8) -> None:
        self.demo = demo
        self.allow_non_demo = (os.environ.get("ALLOW_LOCAL_REPO_EXEC", "").lower() in ("1", "true", "yes")
                               if allow_non_demo is None else allow_non_demo)
        self._slots = asyncio.Semaphore(concurrency)

    async def open(self, files: dict[str, str], *, language_hint: str | None = None,
                   demo: bool | None = None) -> LocalWorkspace:
        is_demo = demo if demo is not None else (self.demo if self.demo is not None else is_demo_files(files))
        if not is_demo and not self.allow_non_demo:
            raise WorkspaceError(
                "local execution is limited to the bundled demo repositories; set ALLOW_LOCAL_REPO_EXEC=1 "
                "or use Nebius Sandboxes (live mode) for other repositories")
        return await asyncio.to_thread(LocalWorkspace.create, files, self._slots, language_hint)


# ---- nebius (contree) -------------------------------------------------------------------------------------

def image_for(language_hint: str | None, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    hint = (language_hint or "").lower()
    python = env.get("PYTHON_IMAGE") or "docker.io/library/python:3.12-slim"
    node = env.get("NODE_IMAGE") or "docker.io/library/node:20-slim"
    if hint in ("ui", "browser", "chromium"):
        return env.get("UI_IMAGE") or node
    if hint in ("node", "javascript", "typescript", "js", "ts", "tsx"):
        return node
    if hint == "go":
        return env.get("GO_IMAGE") or "docker.io/library/golang:1.22"
    return python


class NebiusWorkspace(_BaseWorkspace):
    """Contree-backed workspace. State = checkpoint image + an in-memory overlay of written files.

    `exec` forks the (install-advanced) image into a disposable instance, uploads the overlay under /work and runs
    the allow-listed command there. See the module docstring for what is unverified live.
    """

    isolation = "nebius"
    WORKDIR = "/work"

    def __init__(self, image: Any, files: dict[str, str], originals: dict[str, str], slots: asyncio.Semaphore,
                 language_hint: str | None = None) -> None:
        super().__init__(originals)
        self._image = image
        self._files = dict(files)
        self._deleted: set[str] = {p for p in originals if p not in files}
        self._slots = slots
        self.language_hint = language_hint
        self._installed = False

    def _sizes(self) -> dict[str, int]:
        return {p: len(t.encode("utf-8", errors="replace")) for p, t in self._files.items()}

    async def list_dir(self, path: str = ".") -> list[str]:
        rel = norm_path(path)
        prefix = "" if rel == "." else rel + "/"
        names: set[str] = set()
        for p in self._files:
            if p.startswith(prefix):
                head, _, rest = p[len(prefix):].partition("/")
                names.add(prefix + head + ("/" if rest else ""))
        if not names and rel != "." and rel not in self._files:
            raise FileNotFoundError(f"not a directory: {rel}")
        return sorted(names)[:500]

    async def read(self, path: str, start: int | None = None, end: int | None = None) -> str:
        rel = norm_path(path)
        if rel not in self._files:
            raise FileNotFoundError(f"no such file: {rel}")
        return slice_lines(self._files[rel], start, end)

    async def write(self, path: str, text: str) -> None:
        rel = self._check_mutation(path, text)
        await self._store(rel, text)
        self.writes += 1

    async def _store(self, rel: str, text: str) -> None:
        self._check_caps(rel, text, self._sizes())
        self._files[rel] = text
        self._deleted.discard(rel)

    async def exists(self, path: str) -> bool:
        rel = norm_path(path)
        return rel in self._files or (rel == "node_modules" and self._installed)

    async def delete(self, path: str) -> None:
        rel = self._check_mutation(path, None)
        if rel not in self._files:
            raise FileNotFoundError(f"no such file: {rel}")
        del self._files[rel]
        self._deleted.add(rel)
        self.writes += 1

    async def search(self, pattern: str, glob: str | None = None, limit: int = 50) -> list[tuple[str, int, str]]:
        return self._search_text(sorted(self._files.items()), pattern, glob, min(max(limit, 1), 500))

    async def snapshot(self) -> dict[str, str]:
        return dict(self._files)

    async def changed(self) -> dict[str, str | None]:
        diff: dict[str, str | None] = {p: t for p, t in self._files.items() if self._orig.get(p) != t}
        diff.update({p: None for p in self._deleted if p in self._orig})
        return diff

    def _overlay(self) -> tuple[dict[str, bytes], str]:
        files = {f"{self.WORKDIR}/{p}": t.encode() for p, t in self._files.items()
                 if self._orig.get(p) != t}
        rm = " ".join(f"'{p}'" for p in sorted(self._deleted) if p in self._orig and "'" not in p)
        return files, (f"rm -f {rm} ; " if rm else "")

    @staticmethod
    def _quote(argv: list[str]) -> str:
        import shlex

        return " ".join(shlex.quote(a) for a in argv)

    async def exec(self, cmd: str, timeout: int = 120) -> ExecResult:
        t0 = time.monotonic()
        try:
            steps = parse_command(cmd, self.isolation)
        except ExecDenied as exc:
            return ExecResult(DENIED_EXIT, f"COMMAND_DENIED: {exc}", 0)
        timeout = max(1, min(int(timeout), EXEC_TIMEOUT_MAX))
        persist = any(is_install(s) for s in steps)
        files, rm_prefix = self._overlay()
        body = " && ".join(
            (f"cd {self.WORKDIR}/{s.cwd} && " if s.cwd != "." else "") + self._quote(s.argv) for s in steps)
        shell = f"cd {self.WORKDIR} && {rm_prefix}{body} 2>&1"
        try:
            async with self._slots:
                res = await self._image.run(shell=shell, files=files, disposable=not persist, timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return ExecResult(1, f"SANDBOX_ERROR: {type(exc).__name__}: {exc}", int((time.monotonic() - t0) * 1000))
        if persist and getattr(res, "uuid", None) and int(res.exit_code) == 0:
            self._image = res  # later execs/forks start from the image that has the dependencies installed
            self._installed = True
        from app.sandbox import to_text

        out = to_text(getattr(res, "stdout", None)) + to_text(getattr(res, "stderr", None))
        return ExecResult(int(res.exit_code), tail(out), int((time.monotonic() - t0) * 1000))

    async def fork(self) -> "NebiusWorkspace":
        other = NebiusWorkspace(self._image, self._files, self._orig, self._slots, self.language_hint)
        other._deleted = set(self._deleted)
        other._installed = self._installed
        self._copy_hooks(other)
        return other

    async def release(self) -> None:
        return None  # instances are disposable; checkpoint images are garbage collected by the platform


class NebiusWorkspaceFactory:
    """One checkpoint image per repo (base image + all files at /work); forks share it."""

    def __init__(self, *, client: Any = None, concurrency: int = 8, timeout: int = 180) -> None:
        self._client = client
        self._slots = asyncio.Semaphore(concurrency)
        self._timeout = timeout
        self._base: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def _get_client(self) -> Any:
        if self._client is None:
            from contree_sdk import Contree  # reads NEBIUS_API_KEY / NEBIUS_PROJECT_ID

            self._client = Contree()
        return self._client

    async def _base_image(self, ref: str) -> Any:
        async with self._lock:
            if ref not in self._base:
                self._base[ref] = await self._get_client().images.oci(ref)
            return self._base[ref]

    async def open(self, files: dict[str, str], *, language_hint: str | None = None) -> NebiusWorkspace:
        if len(files) > MAX_FILES:
            raise WorkspaceError(f"too many files: {len(files)} > {MAX_FILES}")
        base = await self._base_image(image_for(language_hint))
        try:
            async with self._slots:
                snap = await base.run(
                    shell="true", files={f"{NebiusWorkspace.WORKDIR}/{p}": t.encode() for p, t in files.items()},
                    disposable=False, timeout=self._timeout,
                )
        except Exception as exc:
            raise WorkspaceError(f"could not create the sandbox checkpoint: {type(exc).__name__}: {exc}") from None
        image = snap if getattr(snap, "uuid", None) else base
        return NebiusWorkspace(image, files, dict(files), self._slots, language_hint)


def default_factory(*, live: bool, demo: bool | None = None, client: Any = None) -> WorkspaceFactory:
    """Nebius when live and credentials exist, otherwise the local (labelled) workspace."""
    if live and (client is not None or (os.environ.get("NEBIUS_API_KEY") and os.environ.get("NEBIUS_PROJECT_ID"))):
        return NebiusWorkspaceFactory(client=client)  # type: ignore[return-value]
    return LocalWorkspaceFactory(demo=demo)  # type: ignore[return-value]
