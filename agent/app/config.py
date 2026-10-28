"""Environment settings and search constants."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = AGENT_DIR / "runs"

BRANCH = 3
BEAM = 2
MAX_DEPTH = 3
LOCAL_TEST_TIMEOUT = 20
SANDBOX_TEST_TIMEOUT = 60

NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
PYTHON_IMAGE = "docker.io/library/python:3.12-slim"
MODES = ("fake", "hybrid", "live")


def _env(name: str, default: str = "") -> str:
    # Strip inline comments like `fake   # fake | hybrid | live`.
    return os.environ.get(name, default).split("#", 1)[0].strip()


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
    max_live_runs: int = 15
    github_token: str = field(default="", repr=False)
    github_repo: str = ""
    runs_dir: Path = RUNS_DIR

    @property
    def llm_ready(self) -> bool:
        return bool(self.nebius_api_key and self.model_nano)

    @property
    def sandbox_ready(self) -> bool:
        return bool(self.nebius_api_key and self.nebius_project_id)


def load_env() -> None:
    load_dotenv(AGENT_DIR / ".env", override=False)


def load_settings() -> Settings:
    load_env()
    mode = _env("PATCHLOOP_MODE", "fake").lower()
    return Settings(
        port=int(_env("PORT", "8001") or 8001),
        shared_secret=_env("AGENT_SHARED_SECRET", "change-me"),
        backend_callback_url=_env("BACKEND_CALLBACK_URL").rstrip("/"),
        nebius_api_key=_env("NEBIUS_API_KEY"),
        nebius_project_id=_env("NEBIUS_PROJECT_ID"),
        model_nano=_env("MODEL_NANO"),
        model_super=_env("MODEL_SUPER"),
        model_ultra=_env("MODEL_ULTRA"),
        mode=mode if mode in MODES else "fake",
        max_live_runs=int(_env("MAX_LIVE_RUNS", "15") or 15),
        github_token=_env("GITHUB_TOKEN"),
        github_repo=_env("GITHUB_REPO"),
    )
