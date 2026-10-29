#!/bin/sh
# Start the agent. With NEW_RELIC_LICENSE_KEY set, run under newrelic-admin so APM, distributed
# tracing (W3C traceparent) and AI monitoring (openai + langchain_core auto-instrumentation) are on.
# Without the key New Relic is not loaded at all.
set -e
cd "$(dirname "$0")/.."
PORT="${PORT:-8001}"
HOST="${HOST:-0.0.0.0}"
if [ -n "$NEW_RELIC_LICENSE_KEY" ]; then
  export NEW_RELIC_APP_NAME="${NEW_RELIC_APP_NAME:-patchloop-agent}"
  export NEW_RELIC_AI_MONITORING_ENABLED="${NEW_RELIC_AI_MONITORING_ENABLED:-true}"
  export NEW_RELIC_DISTRIBUTED_TRACING_ENABLED="${NEW_RELIC_DISTRIBUTED_TRACING_ENABLED:-true}"
  export NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED="${NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED:-true}"
  exec newrelic-admin run-program uvicorn app.main:app --host "$HOST" --port "$PORT"
fi
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
