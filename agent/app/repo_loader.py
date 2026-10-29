"""Load a repository snapshot: the real GitHub tarball (per-run token) or a bundled offline demo repo.

Tarball extraction is defensive: only regular files are kept (symlinks, hardlinks, devices are skipped),
every member path is normalised and rejected if absolute or containing `..` (zip-slip), nothing is ever
written to disk here (we read into memory), and the byte/file caps are enforced while streaming.
"""
from __future__ import annotations

import io
import json
import logging
import tarfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEMO_DIR = Path(__file__).resolve().parent / "demo_repos"
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_FILES = 3000
MAX_FILE_BYTES = 200 * 1024
GITHUB_API = "https://api.github.com"
SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "target", "__pycache__", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", ".idea", ".vscode", "site-packages", ".next", "coverage",
}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".7z",
    ".jar", ".class", ".so", ".dll", ".dylib", ".exe", ".bin", ".o", ".a", ".pyc", ".pyo", ".woff", ".woff2",
    ".ttf", ".eot", ".mp3", ".mp4", ".mov", ".avi", ".webm", ".webp", ".svgz", ".lock", ".sqlite", ".db",
    ".parquet", ".onnx", ".pt", ".pkl", ".wasm",
}


class RepoError(Exception):
    """A user-presentable repo loading failure. Never contains the token."""


@dataclass
class RepoSnapshot:
    full_name: str
    branch: str
    files: dict[str, str]
    truncated: bool = False
    demo: bool = False
    language: str = "unknown"
    test_command: str = ""
    framework: str = ""
    support: str = "none"  # full | best-effort | none
    meta: dict[str, Any] = field(default_factory=dict)


def clean_path(raw: str) -> str | None:
    """Normalised repo-relative POSIX path, or None if unsafe (absolute, traversal, NUL, backslash tricks)."""
    if not raw or "\x00" in raw or "\\" in raw:
        return None
    if raw.startswith(("/", "~")) or ".." in raw.split("/"):
        return None
    parts = [x for x in raw.split("/") if x not in (".", "")]
    return "/".join(parts) or None


def _skip(path: str) -> bool:
    parts = path.split("/")
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return True
    return PurePosixPath(path).suffix.lower() in BINARY_EXT


def extract_tarball(data: bytes) -> tuple[dict[str, str], bool]:
    """(files, truncated) from a GitHub tarball. The single top-level directory is stripped."""
    files: dict[str, str] = {}
    truncated = False
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError as exc:
        raise RepoError(f"not a valid tarball: {type(exc).__name__}") from None
    with tar:
        total = 0
        for member in tar:
            if not member.isreg():  # symlinks, hardlinks, devices, dirs: never followed
                continue
            name = member.name
            if "/" not in name:
                continue
            rel = clean_path(name.split("/", 1)[1])
            if rel is None or _skip(rel) or member.size > MAX_FILE_BYTES:
                continue
            if len(files) >= MAX_FILES or total + member.size > MAX_DOWNLOAD_BYTES:
                truncated = True
                break
            handle = tar.extractfile(member)
            if handle is None:
                continue
            raw = handle.read(MAX_FILE_BYTES + 1)
            if b"\x00" in raw[:8192]:
                continue
            try:
                files[rel] = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            total += len(raw)
    return files, truncated


async def fetch_github(full_name: str, branch: str, token: str, client: httpx.AsyncClient | None = None) -> RepoSnapshot:
    """Download `GET /repos/{full_name}/tarball/{branch}` with the per-run token and extract it."""
    url = f"{GITHUB_API}/repos/{full_name}/tarball/{branch}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "patchloop-agent"}
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True)
    try:
        buf = bytearray()
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code in (401, 403):
                raise RepoError(f"GitHub refused access to {full_name} (HTTP {resp.status_code})")
            if resp.status_code == 404:
                raise RepoError(f"repository or branch not found: {full_name}@{branch}")
            if resp.status_code >= 400:
                raise RepoError(f"GitHub returned HTTP {resp.status_code} for the tarball")
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_DOWNLOAD_BYTES:
                    raise RepoError("repository is larger than the 25 MB limit")
    except httpx.HTTPError as exc:
        raise RepoError(f"could not download the repository: {type(exc).__name__}") from None
    finally:
        if own:
            await client.aclose()
    files, truncated = extract_tarball(bytes(buf))
    if not files:
        raise RepoError("repository has no readable text files")
    snap = RepoSnapshot(full_name=full_name, branch=branch, files=files, truncated=truncated)
    apply_detection(snap)
    return snap


# ---- demo repos -----------------------------------------------------------------------

def demo_names() -> list[str]:
    return sorted(p.name for p in DEMO_DIR.iterdir() if (p / "meta.json").is_file()) if DEMO_DIR.is_dir() else []


def _read_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                out[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return out


def demo_meta(name: str) -> dict[str, Any]:
    return json.loads((DEMO_DIR / name / "meta.json").read_text(encoding="utf-8"))


def list_demo_repos() -> list[dict[str, Any]]:
    out = []
    for name in demo_names():
        meta = demo_meta(name)
        out.append({"full_name": f"demo/{name}", "default_branch": meta.get("default_branch", "main"),
                    "description": meta.get("description", ""), "language": "Python",
                    "default_task": meta.get("default_task", "")})
    return out


def resolve_demo_name(full_name: str) -> str | None:
    short = full_name.split("/", 1)[-1].lower()
    names = demo_names()
    return short if short in names else None


def load_demo(name: str, branch: str = "main") -> RepoSnapshot:
    if name not in demo_names():
        raise RepoError(f"unknown demo repo {name!r}; available: {', '.join(demo_names())}")
    base = DEMO_DIR / name
    meta = demo_meta(name)
    snap = RepoSnapshot(full_name=f"demo/{name}", branch=branch or "main", files=_read_tree(base / "repo"),
                        demo=True, meta=meta)
    snap.meta["fixes"] = {v: _read_tree(base / "fixes" / v) for v in ("partial", "wrong", "correct")}
    snap.meta["repro_text"] = _read_tree(base / "repro")
    apply_detection(snap)
    return snap


def apply_detection(snap: RepoSnapshot) -> None:
    from app.repo_detect import detect

    info = detect(snap.files)
    snap.language, snap.test_command = info["language"], info["test_command"]
    snap.framework, snap.support = info["framework"], info["support"]
