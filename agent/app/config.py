"""Environment settings and search constants."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = AGENT_DIR / "runs"
CACHE_DIR = AGENT_DIR / ".cache"
GUARDRAILS_DIR = AGENT_DIR / "guardrails"

BRANCH = 3
BEAM = 2
MAX_DEPTH = 3
LOCAL_TEST_TIMEOUT = 20
SANDBOX_TEST_TIMEOUT = 60

NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
PYTHON_IMAGE = "docker.io/library/python:3.12-slim"
MODES = ("fake", "hybrid", "live")
ENGINES = ("graph", "loop")


def _env(name: str, default: str = "") -> str:
    # Strip inline comments like `fake   # fake | hybrid | live`.
    return os.environ.get(name, default).split("#", 1)[0].strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)) or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)) or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    port: int = 8001
    shared_secret: str = "change-me"
    backend_callback_url: str = ""
    nebius_api_key: str = field(default="", repr=False)
    nebius_project_id: str = ""
    model_nano: str = ""
    model_super: str = ""
    model_ultra: str = ""
    mode: str = "fake"
    engine: str = "graph"
    max_live_runs: int = 15
    github_token: str = field(default="", repr=False)
    github_repo: str = ""
    runs_dir: Path = RUNS_DIR
    # LangGraph team engine
    max_rounds: int = 3
    llm_max_tokens: int = 900
    llm_timeout: float = 30.0
    # Budgets per run (exceeding stops the run with an error event)
    run_max_tokens: int = 60000
    run_max_seconds: float = 120.0
    run_max_candidates: int = 12
    # Guardrails
    guard_backend: str = "auto"  # auto | heuristic | self | nebius | nvidia
    guard_fail_mode: str = ""  # closed | open; empty = closed for live/hybrid, open for fake/replay
    guard_timeout: float = 2.5
    nvidia_api_key: str = field(default="", repr=False)
    # Policy gate
    max_diff_lines: int = 60
    # Fake mode pacing multiplier (tests use a small value)
    fake_delay_scale: float = 1.0
    # Observability
    langsmith_api_key: str = field(default="", repr=False)
    langsmith_project: str = "patchloop"
    new_relic_license_key: str = field(default="", repr=False)
    sandbox_concurrency: int = 8

    @property
    def llm_ready(self) -> bool:
        return bool(self.nebius_api_key and self.model_nano)

    @property
    def sandbox_ready(self) -> bool:
        return bool(self.nebius_api_key and self.nebius_project_id)

    def fail_mode_for(self, mode: str) -> str:
        if self.guard_fail_mode in ("closed", "open"):
            return self.guard_fail_mode
        return "open" if mode in ("fake", "replay") else "closed"


def load_env() -> None:
    load_dotenv(AGENT_DIR / ".env", override=False)


def load_settings() -> Settings:
    load_env()
    mode = _env("PATCHLOOP_MODE", "fake").lower()
    engine = _env("PATCHLOOP_ENGINE", "graph").lower()
    return Settings(
        port=_int("PORT", 8001),
        shared_secret=_env("AGENT_SHARED_SECRET", "change-me"),
        backend_callback_url=_env("BACKEND_CALLBACK_URL").rstrip("/"),
        nebius_api_key=_env("NEBIUS_API_KEY"),
        nebius_project_id=_env("NEBIUS_PROJECT_ID"),
        model_nano=_env("MODEL_NANO"),
        model_super=_env("MODEL_SUPER"),
        model_ultra=_env("MODEL_ULTRA"),
        mode=mode if mode in MODES else "fake",
        engine=engine if engine in ENGINES else "graph",
        max_live_runs=_int("MAX_LIVE_RUNS", 15),
        github_token=_env("GITHUB_TOKEN"),
        github_repo=_env("GITHUB_REPO"),
        max_rounds=_int("MAX_ROUNDS", 3),
        llm_max_tokens=_int("LLM_MAX_TOKENS", 900),
        llm_timeout=_float("LLM_TIMEOUT", 30.0),
        run_max_tokens=_int("RUN_MAX_TOKENS", 60000),
        run_max_seconds=_float("RUN_MAX_SECONDS", 120.0),
        run_max_candidates=_int("RUN_MAX_CANDIDATES", 12),
        guard_backend=(_env("GUARD_BACKEND", "auto") or "auto").lower(),
        guard_fail_mode=_env("GUARD_FAIL_MODE").lower(),
        guard_timeout=_float("GUARD_TIMEOUT", 2.5),
        nvidia_api_key=_env("NVIDIA_API_KEY"),
        max_diff_lines=_int("POLICY_MAX_DIFF_LINES", 60),
        fake_delay_scale=_float("FAKE_DELAY_SCALE", 1.0),
        langsmith_api_key=_env("LANGSMITH_API_KEY"),
        langsmith_project=_env("LANGSMITH_PROJECT", "patchloop") or "patchloop",
        new_relic_license_key=_env("NEW_RELIC_LICENSE_KEY"),
        sandbox_concurrency=_int("SANDBOX_CONCURRENCY", 8),
    )
