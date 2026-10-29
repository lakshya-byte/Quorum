"""Input/output guard on NVIDIA NeMo Guardrails (rails-only checks, never generation).

Backend is probed once at startup, in this order (GUARD_BACKEND=auto):
  1. nebius    GET {nebius}/models lists a Nemotron safety/guard model -> NeMo content-safety rail
  2. nvidia    NVIDIA_API_KEY set and its model list has a Nemotron content-safety model -> same, engine nim
  3. self      NeMo self-check input/output rails using MODEL_NANO
  4. heuristic fake mode / no LLM credentials: deterministic regex rail, offline, labelled "heuristic"
The heuristic rail always runs first in every backend (cheap, deterministic defence in depth).

Input rail: the bug report and source text are UNTRUSTED; block prompt injection.
Output rail: PR text only. Each check has a timeout (GUARD_TIMEOUT, default 2.5s); on timeout or
error GUARD_FAIL_MODE decides (closed = block, open = pass). Every check returns a guard event.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.config import GUARDRAILS_DIR, NEBIUS_BASE_URL, NVIDIA_BASE_URL, Settings
from app.telemetry import record_event, span

log = logging.getLogger(__name__)

PROBE_TIMEOUT = 2.5
GUARD_MODEL_HINTS = ("safety", "guard", "nemoguard")

INPUT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in [
    ("override instructions", r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|system)\b[^.\n]{0,20}\b(instructions?|prompts?|rules|guidelines|directions)"),
    ("role hijack", r"\b(you are now|from now on,? you|act as|pretend to be)\b[^.\n]{0,40}\b(admin|root|developer mode|dan|unrestricted|jailbroken|system)"),
    ("system prompt probe", r"\b(reveal|print|show|repeat|leak)\b[^.\n]{0,30}\b(system prompt|your prompt|your instructions|hidden instructions)"),
    ("push or merge to main", r"\b(push|merge|commit|force[- ]push)\b[^.\n]{0,30}\b(to|into|on)\s+(the\s+)?(main|master|production)\b"),
    ("tamper with tests", r"\b(delete|remove|modify|edit|rewrite|change|skip|disable|comment out)\b[^.\n]{0,20}\b(the\s+)?(unit\s+)?tests?\b(?![\s\w]{0,15}\b(fail|pass|show|expect))"),
    ("exfiltrate secrets", r"\b(print|send|post|upload|exfiltrate|leak|reveal|echo|dump)\b[^.\n]{0,40}\b(api[_ -]?keys?|secrets?|tokens?|passwords?|credentials?|env(ironment)? vars?|os\.environ)"),
    ("remote code", r"\b(curl|wget)\s+https?://|\bpip install\s+https?://|\|\s*(sh|bash)\b"),
    ("chat template injection", r"<\|im_start\|>|<\|system\|>|\[INST\]|^\s*#{2,}\s*system\s*:|BEGIN SYSTEM PROMPT"),
]]
OUTPUT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in [
    ("secret-like token", r"\b(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abpr]-[A-Za-z0-9-]{10,})"),
    ("auto-merge instruction", r"\b(auto[- ]?merge|merge (this|it) (automatically|without review)|skip (the )?review|no review needed)\b"),
    ("override instructions", INPUT_PATTERNS[0][1].pattern),
    ("remote code", INPUT_PATTERNS[6][1].pattern),
]]


def heuristic_reasons(stage: str, text: str) -> list[str]:
    patterns = INPUT_PATTERNS if stage == "input" else OUTPUT_PATTERNS
    return [f"heuristic: {name}" for name, rx in patterns if rx.search(text or "")]


async def heuristic_check(stage: str = "input", context: dict | None = None) -> bool:
    """NeMo custom action used by the `heuristic check input/output` flows."""
    ctx = context or {}
    text = ctx.get("user_message" if stage == "input" else "bot_message") or ""
    return bool(heuristic_reasons(stage, text))


def _load_base() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    cfg = yaml.safe_load(Path(GUARDRAILS_DIR, "config.yml").read_text(encoding="utf-8"))
    colang = Path(GUARDRAILS_DIR, "rails.co").read_text(encoding="utf-8")
    prompts = yaml.safe_load(Path(GUARDRAILS_DIR, "prompts.yml").read_text(encoding="utf-8"))["prompts"]
    return cfg, colang, prompts


def build_rails_config(backend: str, settings: Settings, guard_model: str = "") -> Any:
    """RailsConfig for a backend. No secrets are written: keys are read from env by NeMo."""
    from nemoguardrails import RailsConfig

    cfg, colang, prompts = _load_base()
    models: list[dict[str, Any]] = []
    if backend in ("self", "nebius"):
        models.append({
            "type": "main", "engine": "openai", "model": settings.model_nano,
            "api_key_env_var": "NEBIUS_API_KEY", "parameters": {"base_url": NEBIUS_BASE_URL},
        })
    if backend == "self":
        cfg["rails"]["input"]["flows"].append("self check input")
        cfg["rails"]["output"]["flows"].append("self check output")
        cfg["prompts"] = [p for p in prompts if p["task"].startswith("self_check")]
    elif backend in ("nebius", "nvidia"):
        cs: dict[str, Any] = {"type": "content_safety", "model": guard_model}
        if backend == "nebius":
            cs.update(engine="openai", api_key_env_var="NEBIUS_API_KEY", parameters={"base_url": NEBIUS_BASE_URL})
        else:
            cs.update(engine="nim", api_key_env_var="NVIDIA_API_KEY", parameters={"base_url": NVIDIA_BASE_URL})
        models.append(cs)
        cfg["rails"]["input"]["flows"].append("content safety check input $model=content_safety")
        cfg["rails"]["output"]["flows"].append("content safety check output $model=content_safety")
        cfg["prompts"] = [p for p in prompts if p["task"].startswith("content_safety")]
    if models:
        cfg["models"] = models
    return RailsConfig.from_content(colang_content=colang, yaml_content=yaml.safe_dump(cfg))


def make_rails(config: Any) -> Any:
    from nemoguardrails import LLMRails

    rails = LLMRails(config)
    rails.register_action(heuristic_check, name="heuristic_check")
    return rails


async def _list_models(url: str, api_key: str) -> list[str]:
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
        resp = await client.get(f"{url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
        return [m.get("id", "") for m in resp.json().get("data", [])]


def pick_guard_model(ids: list[str]) -> str:
    """Prefer Nemotron content-safety models; any id with safety/guard/nemoguard otherwise."""
    hits = [i for i in ids if any(h in i.lower() for h in GUARD_MODEL_HINTS)]
    hits.sort(key=lambda i: ("content" not in i.lower(), "nemotron" not in i.lower() and "nemoguard" not in i.lower(), i))
    return hits[0] if hits else ""


class GuardService:
    """One per process. `heuristic` rails always exist; `model` rails only for a live backend."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = "heuristic"
        self.guard_model = ""
        self.probe_log: list[str] = []
        self._heuristic: Any = None
        self._model: Any = None
        self.nemo_ok = True

    async def startup(self) -> None:
        """Probe the backend, build the rails once and warm them up."""
        try:
            self._heuristic = make_rails(build_rails_config("heuristic", self.settings))
        except Exception as exc:  # nemoguardrails broken: keep the plain regex path
            self.nemo_ok = False
            log.warning("nemoguardrails unavailable (%s); using the plain heuristic guard", type(exc).__name__)
        backend, model = await self.probe()
        if backend != "heuristic":
            try:
                self._model = make_rails(build_rails_config(backend, self.settings, model))
                self.backend, self.guard_model = backend, model
            except Exception as exc:
                self.probe_log.append(f"{backend}: rails build failed ({type(exc).__name__})")
                self.backend = "heuristic"
        log.info("guard backend: %s%s (%s)", self.backend,
                 f" model={self.guard_model}" if self.guard_model else "", "; ".join(self.probe_log) or "-")
        await self.check("input", "warm-up: the function returns the wrong value", "fake")

    async def probe(self) -> tuple[str, str]:
        s = self.settings
        forced = s.guard_backend if s.guard_backend != "auto" else ""
        if s.mode == "fake" or not s.llm_ready:
            if forced and forced != "heuristic":
                self.probe_log.append(f"GUARD_BACKEND={forced} ignored: fake mode or no LLM credentials")
            return "heuristic", ""
        if forced == "heuristic":
            return "heuristic", ""
        if forced in ("", "nebius"):
            try:
                model = pick_guard_model(await _list_models(NEBIUS_BASE_URL, s.nebius_api_key))
                if model:
                    return "nebius", model
                self.probe_log.append("nebius: no safety/guard model listed")
            except Exception as exc:
                self.probe_log.append(f"nebius: probe failed ({type(exc).__name__})")
        if forced in ("", "nvidia") and s.nvidia_api_key:
            try:
                model = pick_guard_model(await _list_models(NVIDIA_BASE_URL, s.nvidia_api_key))
                if model:
                    return "nvidia", model
                self.probe_log.append("nvidia: no content-safety model listed")
            except Exception as exc:
                self.probe_log.append(f"nvidia: probe failed ({type(exc).__name__})")
        elif forced in ("", "nvidia"):
            self.probe_log.append("nvidia: NVIDIA_API_KEY not set")
        return "self", s.model_nano

    def backend_for(self, mode: str) -> str:
        return self.backend if mode in ("live", "hybrid") and self._model is not None else "heuristic"

    async def _rails_check(self, rails: Any, stage: str, text: str) -> tuple[bool, list[str]]:
        from nemoguardrails.rails.llm.options import RailStatus, RailType

        if stage == "input":
            messages = [{"role": "user", "content": text}]
            types = [RailType.INPUT]
        else:
            messages = [{"role": "user", "content": "Write the pull request text."},
                        {"role": "assistant", "content": text}]
            types = [RailType.OUTPUT]
        result = await rails.check_async(messages, rail_types=types)
        if result.status == RailStatus.BLOCKED:
            reasons = heuristic_reasons(stage, text) if "heuristic" in (result.rail or "") else []
            return False, reasons or [f"blocked by rail: {result.rail}"]
        return True, []

    async def check(self, stage: str, text: str, mode: str, run_id: str = "") -> dict[str, Any]:
        """Guard event data: {stage, verdict, reasons, latency_ms, backend}."""
        backend = self.backend_for(mode)
        rails = self._model if backend != "heuristic" else self._heuristic
        fail_mode = self.settings.fail_mode_for(mode)
        t0 = time.monotonic()
        try:
            with span(f"guard.{stage}", group="PatchLoop/Guard"):
                if rails is None:
                    reasons = heuristic_reasons(stage, text)
                    ok = not reasons
                else:
                    ok, reasons = await asyncio.wait_for(self._rails_check(rails, stage, text), self.settings.guard_timeout)
        except asyncio.TimeoutError:
            ok = fail_mode == "open"
            reasons = [f"guard timeout after {self.settings.guard_timeout}s (fail-{fail_mode})"]
        except Exception as exc:
            ok = fail_mode == "open"
            reasons = [f"guard error {type(exc).__name__} (fail-{fail_mode})"]
        event = {
            "stage": stage, "verdict": "pass" if ok else "block", "reasons": reasons,
            "latency_ms": int((time.monotonic() - t0) * 1000), "backend": backend,
        }
        record_event("PatchLoopGuard", {"run_id": run_id, "stage": stage, "verdict": event["verdict"],
                                        "latency_ms": event["latency_ms"], "backend": backend})
        return event
