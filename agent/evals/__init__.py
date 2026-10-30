"""PatchLoop eval pipeline (golden dataset, system-under-test adapter, metrics, DeepEval, Ragas, Streamlit)."""
from __future__ import annotations

import os

# Telemetry stays off for every eval entry point; nothing is sent to Confident AI.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

__version__ = "1.0.0"
