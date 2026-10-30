"""Shared paths, constants and small helpers for the eval package."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
AGENT_DIR = EVALS_DIR.parent
GOLDEN_DIR = EVALS_DIR / "golden"
GOLDEN_PATH = GOLDEN_DIR / "golden_dataset.json"
SCHEMA_PATH = GOLDEN_DIR / "golden.schema.json"
RESULTS_DIR = EVALS_DIR / "results"
BASELINES_DIR = EVALS_DIR / "baselines"
THRESHOLDS_PATH = EVALS_DIR / "thresholds.yaml"

if str(AGENT_DIR) not in sys.path:  # `app.*` imports work however the package is launched
    sys.path.insert(0, str(AGENT_DIR))

NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"

FAKE_BANNER = ("FAKE MODE: scripted agents. These numbers validate the harness (dataset, sandbox, policy gate, "
               "metrics, reports), NOT model quality. Run with --mode hybrid|live and a judge for model results.")

MODES = ("fake", "hybrid", "live")
ENGINES = ("single", "loop", "graph")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_run_id(mode: str = "fake") -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{mode}-{os.urandom(2).hex()}"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def pct(values: list[float], q: float) -> float:
    """Nearest-rank style percentile used across the pipeline (matches scripts/eval.py)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
