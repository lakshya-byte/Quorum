#!/bin/sh
# Start the PatchLoop eval UI (Streamlit). Needs the eval extras: pip install -r requirements-evals.txt
set -e
cd "$(dirname "$0")/.."
PORT="${PORT:-8501}"
exec python -m streamlit run evals/app.py --server.port "$PORT" --server.headless true \
  --browser.gatherUsageStats false "$@"
