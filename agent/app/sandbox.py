"""Isolated test runners: a local subprocess sandbox and Nebius Sandboxes (Contree)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol

from app.config import LOCAL_TEST_TIMEOUT, PYTHON_IMAGE, SANDBOX_TEST_TIMEOUT

log = logging.getLogger(__name__)

TIMEOUT_EXIT = 124
NEBIUS_CONCURRENCY = 8


class Sandbox(Protocol):
    timeout: int

    async def run_tests(self, files: dict[str, str], timeout: int | None = None) -> tuple[int, str]: ...


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
    """Runs unittest in a temp dir via a subprocess with a minimal environment."""

    def __init__(self, timeout: int = LOCAL_TEST_TIMEOUT) -> None:
        self.timeout = timeout

    async def run_tests(self, files: dict[str, str], timeout: int | None = None) -> tuple[int, str]:
        with tempfile.TemporaryDirectory(prefix="patchloop-") as tmp:
            for name, text in files.items():
                Path(tmp, name).write_text(text, encoding="utf-8")
            return await self._run(tmp, timeout or self.timeout)

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
        return proc.returncode or 0, out.decode("utf-8", errors="replace")


class NebiusSandbox:
    """Each test run is a disposable Contree instance forked from a cached python image."""

    def __init__(self, timeout: int = SANDBOX_TEST_TIMEOUT, image: str = PYTHON_IMAGE) -> None:
        self.timeout = timeout
        self._image_ref = image
        self._client: Any = None
        self._base: Any = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(NEBIUS_CONCURRENCY)

    async def prepare(self) -> Any:
        async with self._lock:
            if self._base is None:
                from contree_sdk import Contree

                self._client = Contree()  # reads NEBIUS_API_KEY / NEBIUS_PROJECT_ID
                self._base = await self._client.images.oci(self._image_ref)
            return self._base

    async def run_tests(self, files: dict[str, str], timeout: int | None = None) -> tuple[int, str]:
        try:
            base = await self.prepare()
            async with self._slots:
                res = await base.run(
                    shell="cd /work && python -m unittest discover -s . -p 'test_*.py' 2>&1",
                    files={f"/work/{name}": text.encode() for name, text in files.items()},
                    disposable=True,
                    timeout=timeout or self.timeout,
                )
            return int(res.exit_code), to_text(res.stdout) + to_text(res.stderr)
        except Exception as exc:  # one broken sandbox call must not kill the search
            log.warning("nebius sandbox run failed: %s", type(exc).__name__)
            return 1, f"SANDBOX_ERROR: {type(exc).__name__}: {exc}"
