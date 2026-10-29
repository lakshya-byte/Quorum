#!/usr/bin/env bash
# Stop what scripts/dev-up.sh started (frontend, backend, agent). MongoDB is left running
# (pass --mongo to also stop the pl-mongo container). Portable bash (Linux + macOS).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/.logs"
say() { printf '[dev-down] %s\n' "$*"; }

# Kill a process and its direct children (next dev and uvicorn spawn workers).
kill_tree() {
  local pid="$1" kids
  kids="$(pgrep -P "$pid" 2>/dev/null || true)"
  for k in $kids; do kill_tree "$k"; done
  kill "$pid" 2>/dev/null || true
}

for svc in frontend backend agent; do
  f="$LOGS/$svc.pid"
  if [ -f "$f" ]; then
    pid="$(cat "$f")"
    if kill -0 "$pid" 2>/dev/null; then say "stopping $svc (pid $pid)"; kill_tree "$pid"; fi
    rm -f "$f"
  fi
done

# Anything still holding our ports (e.g. a re-parented worker).
if command -v lsof >/dev/null 2>&1; then
  for p in 3000 8080 8001; do
    pids="$(lsof -ti "tcp:$p" -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$pids" ]; then say "port $p still busy, stopping pid(s) $pids"; kill $pids 2>/dev/null || true; fi
  done
fi

if [ "${1:-}" = "--mongo" ] && command -v docker >/dev/null 2>&1; then
  say "stopping container pl-mongo"; docker stop pl-mongo >/dev/null 2>&1 || true
fi
say "done"
