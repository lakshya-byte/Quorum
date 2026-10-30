#!/usr/bin/env bash
# Stop what scripts/dev-up.sh started (frontend, backend, fake Slack, agent). MongoDB is left running
# (pass --mongo to also stop the pl-mongo container). Portable bash (Linux + macOS).
# Only processes started by dev-up.sh (PID files in .logs) and their children are signalled.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/.logs"
say() { printf '[dev-down] %s\n' "$*"; }

# Print a pid and all its descendants (next dev and uvicorn spawn workers).
tree() {
  local pid="$1" k
  echo "$pid"
  for k in $(pgrep -P "$pid" 2>/dev/null || true); do tree "$k"; done
}

ALL=""
for svc in frontend backend slack agent; do
  f="$LOGS/$svc.pid"
  if [ -f "$f" ]; then
    pid="$(cat "$f")"
    if kill -0 "$pid" 2>/dev/null; then
      pids="$(tree "$pid" | tr '\n' ' ')"
      say "stopping $svc (pid $pids)"
      kill $pids 2>/dev/null || true
      ALL="$ALL $pids"
    fi
    rm -f "$f"
  fi
done

# Graceful shutdown can take a few seconds (uvicorn waits for open streams); then SIGKILL.
alive() { local p out=""; for p in $ALL; do kill -0 "$p" 2>/dev/null && out="$out $p"; done; echo "$out"; }
i=0
while [ -n "$(alive)" ] && [ "$i" -lt 20 ]; do sleep 0.5; i=$((i + 1)); done
left="$(alive)"
if [ -n "$left" ]; then say "still running after 10s, killing:$left"; kill -9 $left 2>/dev/null || true; sleep 0.5; fi

if command -v lsof >/dev/null 2>&1; then
  for p in 3000 8080 8001 19090; do
    holder="$(lsof -ti "tcp:$p" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ')"
    [ -n "$holder" ] && say "note: port $p is held by pid(s) $holder, not started by dev-up.sh (left alone)"
  done
fi

if [ "${1:-}" = "--mongo" ] && command -v docker >/dev/null 2>&1; then
  say "stopping container pl-mongo"; docker stop pl-mongo >/dev/null 2>&1 || true
fi
say "done"
