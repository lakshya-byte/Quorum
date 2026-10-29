"""Isolated test runners: a local subprocess sandbox and Nebius Sandboxes (Contree).

Both expose:
- run_tests(files, timeout) -> (exit_code, output)            (used by the loop engine and scripts)
- check(files, target, timeout) -> (exit_code, output, findings) tests + bandit scan of `target`
- scan(target, code) -> findings | None                          bandit only (baseline of the buggy code)
`findings` is None when no scanner is available.

Networking: contree-sdk 0.3.6 exposes no option to disable networking for an instance
(InstanceSpawnRequest has command/image/env/files/timeout/... but nothing network related),
so Nebius runs keep the platform's default network policy. See README.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol

from app.config import CACHE_DIR, LOCAL_TEST_TIMEOUT, PYTHON_IMAGE, SANDBOX_TEST_TIMEOUT
from app.security import Finding, bandit_local, parse_bandit_json

log = logging.getLogger(__name__)

TIMEOUT_EXIT = 124
NEBIUS_CONCURRENCY = 8
BANDIT_PIN = "bandit==1.9.4"
TOOL_IMAGE_SPEC = f"{PYTHON_IMAGE}+{BANDIT_PIN}"
TOOL_IMAGE_CACHE = CACHE_DIR / "tool_image.json"
SCAN_MARK = "__PATCHLOOP_BANDIT__"


def write_tree(root: str, files: dict[str, str]) -> None:
    """Write files under `root`, refusing any path that would land outside it (defence in depth)."""
    base = Path(root).resolve()
    for name, text in files.items():
        dest = (base / name).resolve()
        if base != dest and base not in dest.parents:
            raise ValueError(f"path escapes the sandbox: {name!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


class Sandbox(Protocol):
    timeout: int

    async def run_tests(self, files: dict[str, str], timeout: int | None = None) -> tuple[int, str]: ...

    async def check(
        self, files: dict[str, str], target: str, timeout: int | None = None,
    ) -> tuple[int, str, list[Finding] | None]: ...

    async def scan(self, target: str, code: str) -> list[Finding] | None: ...


def to_text(stream: Any) -> str:
    """Normalise SDK output that may be str, bytes, a file-like object or None."""
    if stream is None:
        return ""
    if hasattr(stream, "read"):
        if hasattr(stream, "seek"):
            try:
                stream.seek(0)
            except (OSError, ValueError):
                pass
        stream = stream.read()
    if isinstance(stream, (bytes, bytearray)):
        return bytes(stream).decode("utf-8", errors="replace")
    return str(stream)


class LocalSandbox:
    """Runs unittest in a temp dir via a subprocess with a minimal environment (no secrets in env)."""

    label = "an isolated local sandbox"

    def __init__(self, timeout: int = LOCAL_TEST_TIMEOUT, concurrency: int = 8) -> None:
        self.timeout = timeout
        self._slots = asyncio.Semaphore(concurrency)

    async def run_tests(self, files: dict[str, str], timeout: int | None = None) -> tuple[int, str]:
        async with self._slots:
            with tempfile.TemporaryDirectory(prefix="patchloop-") as tmp:
                for name, text in files.items():
                    Path(tmp, name).write_text(text, encoding="utf-8")
                return await self._run(tmp, timeout or self.timeout)

    async def check(
        self, files: dict[str, str], target: str, timeout: int | None = None,
    ) -> tuple[int, str, list[Finding] | None]:
        (code, output), findings = await asyncio.gather(
            self.run_tests(files, timeout), self.scan(target, files[target]),
        )
        return code, output, findings

    async def scan(self, target: str, code: str) -> list[Finding] | None:
        return await bandit_local(Path(target).name, code)

    # ---- whole-repo runs (repo tasks) ------------------------------------------

    async def checkpoint(self, files: dict[str, str]) -> str:
        """Write the repo once; candidates run on a copy of it plus their changed files."""
        root = tempfile.mkdtemp(prefix="patchloop-repo-")
        write_tree(root, files)
        return root

    async def release(self, handle: str | None) -> None:
        if handle and handle.startswith(tempfile.gettempdir()):
            shutil.rmtree(handle, ignore_errors=True)

    async def run_repo(
        self, files: dict[str, str], command: str, timeout: int | None = None, base: str | None = None,
        setup: str = "",
    ) -> tuple[int, str]:
        """Run `command` in a fresh copy of the checkpoint (`base`) with `files` overlaid."""
        async with self._slots:
            with tempfile.TemporaryDirectory(prefix="patchloop-run-") as tmp:
                work = Path(tmp, "w")
                if base:
                    await asyncio.to_thread(shutil.copytree, base, work)
                else:
                    work.mkdir()
                write_tree(str(work), files)
                return await self._run_command(str(work), command, timeout or self.timeout)

    async def _run_command(self, workdir: str, command: str, timeout: int) -> tuple[int, str]:
        argv = shlex.split(command)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": workdir,
               "HOME": workdir, "CI": "1"}
        if argv and argv[0] == "python":
            argv[0] = sys.executable
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=workdir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env,
            )
        except FileNotFoundError:
            return 127, f"SANDBOX_ERROR: command not found: {argv[0] if argv else command}"
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return TIMEOUT_EXIT, "TIMEOUT"
        except asyncio.CancelledError:
            proc.kill()
            raise
        return proc.returncode or 0, out.decode("utf-8", errors="replace")[-20000:]

    async def _run(self, workdir: str, timeout: int) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-m", "unittest", "discover",
            "-s", workdir, "-t", workdir, "-p", "test_*.py",
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return TIMEOUT_EXIT, "TIMEOUT"
        except asyncio.CancelledError:  # early exit: do not leave the test process running
            proc.kill()
            raise
        return proc.returncode or 0, out.decode("utf-8", errors="replace")


def _read_cached_tool_image() -> str | None:
    try:
        data = json.loads(TOOL_IMAGE_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("uuid") if data.get("spec") == TOOL_IMAGE_SPEC else None


def _write_cached_tool_image(uuid: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        TOOL_IMAGE_CACHE.write_text(json.dumps({"spec": TOOL_IMAGE_SPEC, "uuid": uuid}), encoding="utf-8")
    except OSError as exc:
        log.warning("could not cache tool image uuid: %s", exc)


class NebiusSandbox:
    """Each test run is a disposable Contree instance forked from a cached tool image
    (python:3.12-slim + bandit, built once and its UUID cached in agent/.cache)."""

    label = "an isolated Nebius Sandbox"

    def __init__(
        self, timeout: int = SANDBOX_TEST_TIMEOUT, image: str = PYTHON_IMAGE, concurrency: int = NEBIUS_CONCURRENCY,
    ) -> None:
        self.timeout = timeout
        self._image_ref = image
        self._client: Any = None
        self._base: Any = None
        self.has_bandit = False
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(concurrency)

    async def prepare(self) -> Any:
        """Prewarm: resolve (or build once) the tool image. Safe to call many times."""
        async with self._lock:
            if self._base is None:
                from uuid import UUID

                from contree_sdk import Contree

                self._client = Contree()  # reads NEBIUS_API_KEY / NEBIUS_PROJECT_ID
                cached = _read_cached_tool_image()
                if cached:
                    self._base = await self._client.images.use(UUID(cached))
                    self.has_bandit = True
                else:
                    python = await self._client.images.oci(self._image_ref)
                    try:
                        tool = await python.run(
                            shell=f"pip install --no-cache-dir -q {BANDIT_PIN} 2>&1 | tail -2",
                            disposable=False, timeout=300,
                        )
                        if int(tool.exit_code) != 0 or not tool.uuid:
                            raise RuntimeError(f"tool image build exit {tool.exit_code}")
                        _write_cached_tool_image(str(tool.uuid))
                        self._base, self.has_bandit = tool, True
                    except Exception as exc:
                        log.warning("tool image build failed (%s); using plain python image", type(exc).__name__)
                        self._base, self.has_bandit = python, False
                log.info("nebius sandbox ready (bandit=%s)", self.has_bandit)
            return self._base

    async def _exec(self, shell: str, files: dict[str, str], timeout: int) -> tuple[int, str]:
        base = await self.prepare()
        async with self._slots:
            res = await base.run(
                shell=shell,
                files={f"/work/{name}": text.encode() for name, text in files.items()},
                disposable=True,
                timeout=timeout,
            )
        return int(res.exit_code), to_text(res.stdout) + to_text(res.stderr)

    async def run_tests(self, files: dict[str, str], timeout: int | None = None) -> tuple[int, str]:
        try:
            return await self._exec(
                "cd /work && python -m unittest discover -s . -p 'test_*.py' 2>&1", files, timeout or self.timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # one broken sandbox call must not kill the search
            log.warning("nebius sandbox run failed: %s", type(exc).__name__)
            return 1, f"SANDBOX_ERROR: {type(exc).__name__}: {exc}"

    async def check(
        self, files: dict[str, str], target: str, timeout: int | None = None,
    ) -> tuple[int, str, list[Finding] | None]:
        """Tests and bandit in ONE disposable instance (one round trip)."""
        shell = (
            "cd /work && python -m unittest discover -s . -p 'test_*.py' > /tmp/t.out 2>&1; rc=$?; cat /tmp/t.out; "
            f"echo {SCAN_MARK}; (command -v bandit >/dev/null && bandit -f json -q {target} 2>/dev/null) || true; "
            "exit $rc"
        )
        try:
            code, out = await self._exec(shell, files, timeout or self.timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("nebius sandbox run failed: %s", type(exc).__name__)
            return 1, f"SANDBOX_ERROR: {type(exc).__name__}: {exc}", None
        tests, _, scan = out.partition(SCAN_MARK)
        return code, tests, parse_bandit_json(scan) if scan.strip() else None

    async def checkpoint(self, files: dict[str, str]) -> Any:
        """Upload the repo ONCE as a non-disposable instance; candidates fork from the resulting image."""
        base = await self.prepare()
        async with self._slots:
            snap = await base.run(
                shell="true", files={f"/work/{n}": t.encode() for n, t in files.items()},
                disposable=False, timeout=120,
            )
        return snap if getattr(snap, "uuid", None) else base

    async def release(self, handle: Any) -> None:
        return None  # checkpoints are garbage collected by the platform

    async def run_repo(
        self, files: dict[str, str], command: str, timeout: int | None = None, base: Any = None, setup: str = "",
    ) -> tuple[int, str]:
        """Fork the checkpoint, overlay the changed files and run the test command in a disposable instance."""
        image = base or await self.prepare()
        prefix = "python -m pytest --version >/dev/null 2>&1 || pip install -q pytest >/dev/null 2>&1; " \
            if "pytest" in command else ""
        shell = f"cd /work && {setup + ' ; ' if setup else ''}{prefix}{command} 2>&1"
        try:
            async with self._slots:
                res = await image.run(
                    shell=shell, files={f"/work/{n}": t.encode() for n, t in files.items()},
                    disposable=True, timeout=timeout or self.timeout,
                )
            return int(res.exit_code), (to_text(res.stdout) + to_text(res.stderr))[-20000:]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("nebius repo run failed: %s", type(exc).__name__)
            return 1, f"SANDBOX_ERROR: {type(exc).__name__}: {exc}"

    async def scan(self, target: str, code: str) -> list[Finding] | None:
        target = Path(target).name
        try:
            _, out = await self._exec(
                f"cd /work && (command -v bandit >/dev/null && bandit -f json -q {target} 2>/dev/null) || true",
                {target: code}, 60,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("nebius scan failed: %s", type(exc).__name__)
            return None
        return parse_bandit_json(out)
