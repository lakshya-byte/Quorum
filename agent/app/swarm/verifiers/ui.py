"""UI verifiers: build, serve the built app from memory, drive headless chromium (Playwright via node), collect
console errors, per-viewport horizontal overflow, axe-core violation counts and screenshots.

Needs: node + the `playwright` npm package (global) + a chromium build (PLAYWRIGHT_BROWSERS_PATH) on the AGENT host,
and a workspace that can hand back its build output (LocalWorkspace). Anything missing yields an explicit `skip`
reason ("chromium unavailable", "ui checks need a local workspace"...), never a silent pass. The Nebius UI image
(UI_IMAGE with chromium) is unverified; until then UI criteria on Nebius workspaces report `skip`."""
from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.config import CACHE_DIR
from app.swarm.artifacts import ArtifactStore
from app.swarm.repo_map import RepoMap
from app.swarm.verifiers.common import BUILD_TIMEOUT, ensure_installed, state_hash
from app.swarm.verifiers.registry import Ctx, register, result, skip
from app.swarm.verifiers.types import Baseline, Criterion, VerifyResult

PROBE_JS = Path(__file__).resolve().parent / "js" / "ui_probe.js"
TOOLS_DIR = CACHE_DIR / "tools"
AXE_VERSION = "4.10.2"
VIEWPORTS = (375, 768, 1280)
PROBE_TIMEOUT = 150
_axe_lock: asyncio.Lock | None = None
_probe_cache: dict[str, dict] = {}


# ---- environment -----------------------------------------------------------------------------------------

def node_global_modules() -> str | None:
    if os.environ.get("PLAYWRIGHT_NODE_PATH"):
        return os.environ["PLAYWRIGHT_NODE_PATH"]
    node = shutil.which("node")
    if not node:
        return None
    for cand in (Path(node).resolve().parent.parent / "lib" / "node_modules", Path("/usr/lib/node_modules"),
                 Path("/usr/local/lib/node_modules")):
        if (cand / "playwright").is_dir():
            return str(cand)
    return None


def ui_environment() -> tuple[bool, str]:
    """(available, reason). Cheap file checks only; a launch failure is reported by the probe itself."""
    if not shutil.which("node"):
        return False, "node is not installed on the agent host"
    if not node_global_modules():
        return False, "the playwright npm package is not installed (npm i -g playwright)"
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(Path.home() / ".cache" / "ms-playwright")
    if not (Path(base).is_dir() and any(Path(base).glob("chromium*"))):
        return False, f"chromium unavailable (no chromium build under {base})"
    return True, ""


async def ensure_axe() -> Path | None:
    global _axe_lock
    target = TOOLS_DIR / "node_modules" / "axe-core" / "axe.min.js"
    if target.is_file():
        return target
    _axe_lock = _axe_lock or asyncio.Lock()
    async with _axe_lock:
        if target.is_file():
            return target
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        (TOOLS_DIR / "package.json").write_text('{"name":"patchloop-tools","private":true}', encoding="utf-8")
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(TOOLS_DIR), "npm_config_cache": str(CACHE_DIR / "npm-cache"),
               "npm_config_audit": "false", "npm_config_fund": "false"}
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy", "SSL_CERT_FILE",
                  "NODE_EXTRA_CA_CERTS"):
            if os.environ.get(k):
                env[k] = os.environ[k]
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "install", "--no-save", "--prefix", str(TOOLS_DIR), f"axe-core@{AXE_VERSION}",
                cwd=str(TOOLS_DIR), env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), 180)
        except (asyncio.TimeoutError, OSError):
            return None
    return target if target.is_file() else None


# ---- serving + probing -----------------------------------------------------------------------------------

class _MemServer:
    """Serve an in-memory file map on 127.0.0.1:<ephemeral> (no disk, no directory traversal possible)."""

    def __init__(self, files: dict[str, bytes]) -> None:
        mem = {("/" + k.lstrip("/")): v for k, v in files.items()}
        mem.setdefault("/", mem.get("/index.html", b""))

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0].split("#", 1)[0]
                body = mem.get(path)
                if body is None and "." not in path.rsplit("/", 1)[-1]:
                    body = mem.get("/index.html")  # SPA fallback
                    path = "/index.html"
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
                if path == "/":
                    ctype = "text/html"
                self.send_response(200)
                self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or "javascript" in ctype else ""))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "_MemServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _dist_key(files: dict[str, bytes], extra: str) -> str:
    h = hashlib.sha256(extra.encode())
    for k in sorted(files):
        h.update(b"\0" + k.encode() + b"\0" + hashlib.sha256(files[k]).digest())
    return h.hexdigest()


async def run_probe(dist: dict[str, bytes], *, viewports=VIEWPORTS, axe: bool = True, smoke: str | None = None,
                    mode: str = "probe") -> dict[str, Any]:
    """Serve `dist` and run ui_probe.js. Returns the probe JSON (+ `shots` bytes per viewport). Cached by content."""
    ok, why = ui_environment()
    if not ok:
        return {"ok": False, "unavailable": why}
    axe_path = await ensure_axe() if axe and mode != "smoke" else None
    key = _dist_key(dist, json.dumps([viewports, bool(axe_path), smoke, mode]))
    if key in _probe_cache:
        return _probe_cache[key]
    tmp = tempfile.mkdtemp(prefix="patchloop-ui-")
    try:
        smoke_path = None
        if smoke:
            smoke_path = os.path.join(tmp, "smoke.js")
            Path(smoke_path).write_text(smoke, encoding="utf-8")
        with _MemServer(dist) as srv:
            cfg = {"url": srv.url, "outDir": tmp, "viewports": list(viewports), "axePath": str(axe_path) if axe_path else None,
                   "smoke": smoke_path, "mode": mode}
            Path(tmp, "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")
            env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "NODE_PATH": node_global_modules() or "",
                   "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")}
            if not env["PLAYWRIGHT_BROWSERS_PATH"]:
                env.pop("PLAYWRIGHT_BROWSERS_PATH")
            proc = await asyncio.create_subprocess_exec(
                "node", str(PROBE_JS), os.path.join(tmp, "cfg.json"), cwd=tmp, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), PROBE_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                return {"ok": False, "error": "headless probe timed out"}
        rpath = Path(tmp, "result.json")
        if not rpath.is_file():
            return {"ok": False, "error": "probe produced no result: " + out.decode("utf-8", "replace")[-300:]}
        data = json.loads(rpath.read_text(encoding="utf-8"))
        data["shots"] = {}
        for vp, m in (data.get("viewports") or {}).items():
            f = Path(tmp, m.get("screenshot", ""))
            if f.is_file() and f.stat().st_size <= 5 * 1024 * 1024:
                data["shots"][vp] = f.read_bytes()
        data["axe_available"] = bool(axe_path)
        if data.get("ok"):
            _probe_cache[key] = data
            if len(_probe_cache) > 32:
                _probe_cache.pop(next(iter(_probe_cache)))
        return data
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- building -------------------------------------------------------------------------------------------

def is_web_app(rm: RepoMap, files: dict[str, str]) -> bool:
    return "index.html" in files and bool(rm.commands.get("build") or rm.frameworks or "index.html" in files)


async def build_dist(ws: Any, rm: RepoMap, files: dict[str, str]) -> tuple[dict[str, bytes] | None, str, str]:
    """(dist files | None, status 'ok'|'fail'|'skip', detail). Builds with the repo's own build script."""
    if not hasattr(ws, "read_tree_bytes"):
        return None, "skip", "ui checks need a local workspace with chromium (the nebius UI image is unverified)"
    ok, why = ui_environment()
    if not ok:
        return None, "skip", why
    build = rm.commands.get("build", "")
    if build:
        inst_ok, why = await ensure_installed(ws, rm)
        if not inst_ok:
            return None, "fail", why
        res = await ws.exec(build, timeout=BUILD_TIMEOUT)
        if res.code != 0:
            return None, "fail", f"`{build}` failed (exit {res.code}): {res.stdout_tail[-400:]}"
    elif "index.html" in files:  # plain static site: serve the repo as is
        static = {p: t.encode() for p, t in files.items() if p.endswith((".html", ".css", ".js", ".svg", ".json", ".mjs"))}
        return static, "ok", "static site served as is"
    else:
        return None, "skip", "no build script and no index.html"
    for d in ("dist", "build", "out", "public"):
        if await ws.exists(f"{d}/index.html"):
            return await ws.read_tree_bytes(d), "ok", f"built with `{build}` -> {d}/"
    return None, "skip", "the build produced no static index.html (server-rendered app?)"


_ui_cache: dict[str, dict] = {}


async def ui_state(ws: Any, rm: RepoMap, files: dict[str, str]) -> dict[str, Any]:
    """Build + probe the workspace's current state once; cached by file content."""
    key = state_hash(files, "ui")
    if key in _ui_cache:
        return _ui_cache[key]
    dist, status, detail = await build_dist(ws, rm, files)
    state: dict[str, Any] = {"status": status, "detail": detail, "dist": dist}
    if status == "ok" and dist is not None:
        probe = await run_probe(dist)
        if probe.get("unavailable"):
            state.update(status="skip", detail=probe["unavailable"])
        elif not probe.get("ok"):
            state.update(status="fail", detail=f"headless load failed: {probe.get('error')}")
        else:
            state["probe"] = probe
    if state["status"] != "skip" or "unavailable" not in detail:
        _ui_cache[key] = state
    return state


async def collect_ui_baseline(ws: Any, rm: RepoMap, files: dict[str, str]) -> dict[str, Any]:
    if not is_web_app(rm, files):
        return {"status": "skip", "reason": "not a static web app (no index.html)"}
    state = await ui_state(ws, rm, files)
    if state["status"] != "ok":
        return {"status": state["status"], "reason": state["detail"]}
    probe = state["probe"]
    return {"status": "ok", "reason": "", "dist_files": state["dist"], "viewports": probe["viewports"],
            "axe": probe.get("axe"), "console_errors": probe["console_errors"] + probe["page_errors"],
            "shots": probe.get("shots", {}), "axe_available": probe.get("axe_available", False)}


def add_shots(store: ArtifactStore, phase: str, shots: dict[str, bytes]) -> list:
    """Attach screenshots once per (phase, viewport, content)."""
    seen = store.__dict__.setdefault("_shot_seen", {})
    out = []
    for vp, data in sorted(shots.items(), key=lambda t: int(t[0])):
        key = (phase, vp, hashlib.sha1(data).hexdigest())
        if key in seen:
            out.append(seen[key])
            continue
        art = store.add("screenshot", f"{phase} @ {vp}px", phase, vp, "image/png", data)
        if art:
            seen[key] = art
            out.append(art)
    return out


# ---- verifiers --------------------------------------------------------------------------------------------

async def _after(c: Criterion, ctx: Ctx) -> tuple[dict | None, VerifyResult | None, dict]:
    """(state, early result, baseline ui). The early result is a skip/fail that ends the criterion."""
    base_ui = ctx.baseline.ui
    if base_ui.get("status") == "skip" and "not a static web app" in base_ui.get("reason", ""):
        return None, skip(c, base_ui["reason"]), base_ui
    files = await ctx.files()
    rm = await ctx.repo_map()
    if not is_web_app(rm, files):
        return None, skip(c, "not a static web app (no index.html)"), base_ui
    state = await ui_state(ctx.ws, rm, files)
    if state["status"] == "skip":
        return None, skip(c, state["detail"]), base_ui
    if state["status"] == "fail":
        return None, result(c, "fail", state["detail"]), base_ui
    return state, None, base_ui


def _before_after_shots(ctx: Ctx, state: dict) -> list:
    arts = []
    if ctx.baseline.ui.get("shots"):
        arts += add_shots(ctx.store, "before", ctx.baseline.ui["shots"])
    arts += add_shots(ctx.store, "after", state["probe"].get("shots", {}))
    return arts


@register("ui_build_console")
async def ui_build_console(c: Criterion, ctx: Ctx) -> VerifyResult:
    state, early, base = await _after(c, ctx)
    if early:
        return early
    probe = state["probe"]
    errors = probe["console_errors"] + probe["page_errors"]
    before = list(base.get("console_errors") or [])
    arts = _before_after_shots(ctx, state)
    allowed = int(c.params.get("max_errors", len(before)))
    if len(errors) > allowed:
        return result(c, "fail", f"build ok but {len(errors)} console/page error(s) on load (baseline {len(before)}): {errors[0][:160]}",
                      artifacts=arts, errors=errors)
    return result(c, "pass", f"build ok, page loads with {len(errors)} console error(s) (baseline {len(before)})", artifacts=arts)


@register("ui_overflow")
async def ui_overflow(c: Criterion, ctx: Ctx) -> VerifyResult:
    state, early, base = await _after(c, ctx)
    if early:
        return early
    vps = state["probe"]["viewports"]
    arts = _before_after_shots(ctx, state)
    bad = {vp: m for vp, m in vps.items() if m["overflow"]}
    before_bad = {vp for vp, m in (base.get("viewports") or {}).items() if m.get("overflow")}
    if c.params.get("relative"):
        bad = {vp: m for vp, m in bad.items() if vp not in before_bad}
    if bad:
        parts = [f"{vp}px: +{m['overflowPx']}px ({', '.join(m['offenders'][:2])})" for vp, m in sorted(bad.items(), key=lambda t: int(t[0]))]
        return result(c, "fail", "horizontal overflow remains at " + "; ".join(parts) +
                      (f" (before: {sorted(before_bad)})" if before_bad else ""), artifacts=arts, overflow=sorted(bad))
    return result(c, "pass", "no horizontal overflow at " + "/".join(sorted(vps, key=int)) + "px" +
                  (f" (before: overflow at {sorted(before_bad, key=int)})" if before_bad else ""), artifacts=arts)


@register("ui_axe")
async def ui_axe(c: Criterion, ctx: Ctx) -> VerifyResult:
    state, early, base = await _after(c, ctx)
    if early:
        return early
    after = state["probe"].get("axe")
    before = base.get("axe")
    if after is None or before is None:
        return skip(c, "axe-core unavailable (npm install axe-core failed or was skipped)")
    arts = _before_after_shots(ctx, state)
    ids = ", ".join(f"{v['id']}x{v['nodes']}" for v in after["violations"][:5])
    worse = after["rules"] > before["rules"] or after["nodes"] > before["nodes"]
    summary = f"axe violations: rules {before['rules']} -> {after['rules']}, nodes {before['nodes']} -> {after['nodes']}"
    if worse:
        return result(c, "fail", summary + f"; now: {ids}", artifacts=arts, before=before["rules"], after=after["rules"])
    if c.params.get("require_decrease") and not (after["rules"] < before["rules"] or after["nodes"] < before["nodes"]):
        return result(c, "fail", summary + " (task requires a measurable decrease)", artifacts=arts)
    return result(c, "pass", summary + (f"; remaining: {ids}" if ids else "; none remaining"), artifacts=arts,
                  before=before["rules"], after=after["rules"], nodes_before=before["nodes"], nodes_after=after["nodes"])


@register("ui_smoke")
async def ui_smoke(c: Criterion, ctx: Ctx) -> VerifyResult:
    script = c.params.get("script", "")
    if not script:
        return skip(c, "no smoke script provided")
    state, early, base = await _after(c, ctx)
    if early:
        return early
    run = await run_probe(state["dist"], smoke=script, mode="smoke")
    after = run.get("smoke") or {"ok": False, "error": run.get("error") or "no smoke result"}
    before = None
    if base.get("dist_files"):  # the same script must also pass on the ORIGINAL build
        prior = await run_probe(base["dist_files"], smoke=script, mode="smoke")
        before = prior.get("smoke") or {"ok": False, "error": prior.get("error") or "no smoke result"}
    arts = _before_after_shots(ctx, state)
    if before is not None and not before["ok"]:
        return result(c, "fail", f"smoke script does not pass on the ORIGINAL ({before['error']}); it cannot judge the change",
                      artifacts=arts)
    if not after["ok"]:
        return result(c, "fail", f"smoke script fails after the change: {after['error']}", artifacts=arts)
    return result(c, "pass", "smoke script passes before and after" if before is not None else "smoke script passes after (before not run)",
                  artifacts=arts)
