#!/usr/bin/env bash
# End-to-end check against the RUNNING local stack (start it with scripts/dev-up.sh).
# bash + curl + python3 (stdlib) only. Prints a PASS/FAIL table; exits 1 if anything FAILs.
#
#   scripts/e2e.sh
#
# Needs DEV_MODE=true on the backend (OTP read from /internal/dev/otp) and the agent shared secret,
# both set up by dev-up.sh in .logs/dev.env. Override with BACKEND_URL / AGENT_URL / AGENT_SHARED_SECRET.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Values already in the environment win over .logs/dev.env (e.g. against docker compose).
_secret="${AGENT_SHARED_SECRET:-}"; _backend="${BACKEND_URL:-}"
[ -f "$ROOT/.logs/dev.env" ] && . "$ROOT/.logs/dev.env"
[ -n "$_secret" ] && AGENT_SHARED_SECRET="$_secret"
BACKEND_URL="${_backend:-http://localhost:8080}"
AGENT_URL="${AGENT_URL:-http://localhost:8001}"
: "${AGENT_SHARED_SECRET:?AGENT_SHARED_SECRET is not set (run scripts/dev-up.sh first)}"
HARD_BUG="${E2E_HARD_BUG:-version_sort}"
EASY_BUG="${E2E_EASY_BUG:-cart}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/patchloop-e2e.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
JAR="$WORK/cookies.txt"
RESULTS="$WORK/results.tsv"
METRICS="$WORK/metrics.tsv"
: >"$RESULTS"; : >"$METRICS"

C() { curl -s --noproxy '*' --max-time "${CURL_MAX:-20}" "$@"; }
now() { python3 -c 'import time; print(f"{time.time():.6f}")'; }
# json FILE EXPR: evaluate a python expression on the parsed JSON (variable d); empty on error.
json() { python3 -c 'import json,sys
try:
    d=json.load(open(sys.argv[1])); v=eval(sys.argv[2])
    print("" if v is None else (json.dumps(v) if isinstance(v,(dict,list,bool)) else v))
except Exception: print("")' "$1" "$2"; }
rec() { printf '%s\t%s\t%s\n' "$1" "$2" "${3:-}" >>"$RESULTS"; }
ok() { if [ "$2" = "1" ]; then rec "$1" PASS "${3:-}"; else rec "$1" FAIL "${3:-}"; fi; }
# req NAME EXPECTED_STATUS OUTFILE curl-args...: run curl, record PASS/FAIL on the status code.
req() {
  local name="$1" want="$2" out="$3"; shift 3
  local code; code="$(C -o "$out" -w '%{http_code}' "$@")"
  if [ "$code" = "$want" ]; then rec "$name" PASS "HTTP $code"; return 0; fi
  rec "$name" FAIL "HTTP $code (want $want): $(head -c 160 "$out" 2>/dev/null)"; return 1
}
cj=(-b "$JAR" -c "$JAR")
jh=(-H 'Content-Type: application/json')

echo "PatchLoop e2e against $BACKEND_URL (agent $AGENT_URL)"

# ------------------------------------------------------------------ health
req "backend GET /health" 200 "$WORK/h.json" "$BACKEND_URL/health"
AGENT_DIRECT=1
if [ "$(C -o "$WORK/ah.json" -w '%{http_code}' "$AGENT_URL/health")" = 200 ]; then
  AGENT_MODE="$(json "$WORK/ah.json" 'd["mode"]')"
  rec "agent GET /health (internal, direct)" PASS "mode=$AGENT_MODE engine=$(json "$WORK/ah.json" 'd["engine"]') guard=$(json "$WORK/ah.json" 'd["guard_backend"]')"
  code="$(C -o /dev/null -w '%{http_code}' "$AGENT_URL/bugs")"
  ok "agent rejects calls without X-Agent-Secret" "$([ "$code" = 401 ] && echo 1)" "HTTP $code"
else
  AGENT_DIRECT=0
  rec "agent GET /health (internal, direct)" SKIP "$AGENT_URL not reachable from here (internal only, e.g. compose): relay overhead not measured"
fi

# ------------------------------------------------------------------ auth
EMAIL="e2e-$(date +%s)-$$@example.com"
PASSWORD="e2e-password-$$"
req "POST /api/auth/signup" 201 "$WORK/signup.json" "${cj[@]}" "${jh[@]}" -X POST "$BACKEND_URL/api/auth/signup" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"companyName\":\"E2E Inc\"}"
req "GET /internal/dev/otp (DEV_MODE)" 200 "$WORK/otp.json" -H "X-Agent-Secret: $AGENT_SHARED_SECRET" \
  "$BACKEND_URL/internal/dev/otp?email=$EMAIL"
OTP="$(json "$WORK/otp.json" 'd["code"]')"
req "POST /api/auth/verify-otp" 200 "$WORK/verify.json" "${cj[@]}" "${jh[@]}" -X POST "$BACKEND_URL/api/auth/verify-otp" \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$OTP\"}"
rm -f "$JAR"
req "POST /api/auth/login (cookie jar)" 200 "$WORK/login.json" "${cj[@]}" "${jh[@]}" -X POST "$BACKEND_URL/api/auth/login" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
ok "login sets httpOnly access cookie" "$(grep -q patchloop_access_token "$JAR" 2>/dev/null && echo 1)"
req "GET /api/auth/me" 200 "$WORK/me.json" "${cj[@]}" "$BACKEND_URL/api/auth/me"
code="$(C -o "$WORK/noauth.json" -w '%{http_code}' "$BACKEND_URL/api/runs")"
ok "GET /api/runs without auth -> 401 JSON" "$([ "$code" = 401 ] && [ -n "$(json "$WORK/noauth.json" 'd["error"]')" ] && echo 1)" "HTTP $code"

# ------------------------------------------------------------------ bugs
req "GET /api/bugs" 200 "$WORK/bugs.json" "${cj[@]}" "$BACKEND_URL/api/bugs"
NBUGS="$(json "$WORK/bugs.json" 'len(d)')"
HARD_TIER="$(json "$WORK/bugs.json" "next(b['tier'] for b in d if b['id']=='$HARD_BUG')")"
ok "bug list has $HARD_BUG (hard) and $EASY_BUG" "$([ "$HARD_TIER" = hard ] && grep -q "\"$EASY_BUG\"" "$WORK/bugs.json" && echo 1)" "$NBUGS bugs"

# ------------------------------------------------------------------ hard run, graph engine, stream through backend
T0="$(now)"
req "POST /api/runs ($HARD_BUG, engine graph)" 201 "$WORK/run.json" "${cj[@]}" "${jh[@]}" -X POST "$BACKEND_URL/api/runs" \
  -d "{\"bugId\":\"$HARD_BUG\",\"engine\":\"graph\"}"
RUN_ID="$(json "$WORK/run.json" 'd["runId"]')"
ok "create run returns {runId,mode,engine=graph}" "$([ -n "$RUN_ID" ] && [ "$(json "$WORK/run.json" 'd["engine"]')" = graph ] && [ -n "$(json "$WORK/run.json" 'd["mode"]')" ] && echo 1)" "mode=$(json "$WORK/run.json" 'd["mode"]')"
C "${cj[@]}" -o "$WORK/run0.json" "$BACKEND_URL/api/runs/$RUN_ID"
AGENT_RUN="$(json "$WORK/run0.json" 'd["agentRunId"]')"
AGENT_ARGS=()
[ "$AGENT_DIRECT" = 1 ] && AGENT_ARGS=(--agent-events "$AGENT_URL/runs/$AGENT_RUN/events" --agent-secret "$AGENT_SHARED_SECRET")
python3 "$ROOT/scripts/e2e/sse_probe.py" --prefix "hard run SSE" --t0 "$T0" \
  --backend-events "$BACKEND_URL/api/runs/$RUN_ID/events" --cookie-jar "$JAR" "${AGENT_ARGS[@]+"${AGENT_ARGS[@]}"}" >"$WORK/probe.tsv"
grep -v '^METRIC' "$WORK/probe.tsv" >>"$RESULTS"
grep '^METRIC' "$WORK/probe.tsv" | cut -f2- >>"$METRICS"

# Completion callback -> Run saved.
STATUS=""
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  C "${cj[@]}" -o "$WORK/runfinal.json" "$BACKEND_URL/api/runs/$RUN_ID"
  STATUS="$(json "$WORK/runfinal.json" 'd["status"]')"
  [ "$STATUS" = completed ] && break
  sleep 0.5
done
ok "run saved via /internal/runs/:id/complete (status completed)" "$([ "$STATUS" = completed ] && echo 1)" "status=$STATUS"
ok "saved run solved=true, nodes non-empty, bestNodeId set" \
  "$([ "$(json "$WORK/runfinal.json" 'd["solved"]')" = true ] && [ "$(json "$WORK/runfinal.json" 'len(d["nodes"])')" -gt 0 ] 2>/dev/null && [ -n "$(json "$WORK/runfinal.json" 'd["bestNodeId"]')" ] && echo 1)" \
  "nodes=$(json "$WORK/runfinal.json" 'len(d["nodes"])') best=$(json "$WORK/runfinal.json" 'd["bestNodeId"]') latencyMs=$(json "$WORK/runfinal.json" 'd["latencyMs"]')"
C "${cj[@]}" -o "$WORK/runs.json" "$BACKEND_URL/api/runs"
ok "GET /api/runs lists the run" "$([ "$(json "$WORK/runs.json" "any(r['id']=='$RUN_ID' for r in d)")" = true ] && echo 1)"

# PR without GitHub credentials: must be a clean JSON error (not a 500 crash, not a hang).
T1="$(now)"
code="$(CURL_MAX=30 C "${cj[@]}" -o "$WORK/pr.json" -w '%{http_code}' -X POST "$BACKEND_URL/api/runs/$RUN_ID/pr")"
PR_MS="$(python3 -c "import time; print(int((time.time()-$T1)*1000))")"
PR_ERR="$(json "$WORK/pr.json" 'd["error"]')"
if [ "$code" = 200 ]; then
  rec "POST /api/runs/:id/pr" PASS "PR opened: $(json "$WORK/pr.json" 'd["url"]') (GitHub is configured)"
else
  ok "POST /api/runs/:id/pr without GITHUB_TOKEN -> clean JSON error" \
    "$([ "$code" != 000 ] && [ "$code" != 500 ] && [ "$code" -ge 400 ] && [ -n "$PR_ERR" ] && echo 1)" \
    "HTTP $code in ${PR_MS}ms: $PR_ERR"
fi

# ------------------------------------------------------------------ API token + CLI
req "POST /api/tokens" 201 "$WORK/tok.json" "${cj[@]}" "${jh[@]}" -X POST "$BACKEND_URL/api/tokens" -d '{"name":"e2e"}'
TOKEN="$(json "$WORK/tok.json" 'd["token"]')"
ok "token is plk_ prefixed and listed without secret" \
  "$(case "$TOKEN" in plk_*) [ "$(C "${cj[@]}" "$BACKEND_URL/api/tokens" | grep -c "$TOKEN")" = 0 ] && echo 1;; esac)"
code="$(C -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/api/auth/me")"
ok "Bearer plk_ token authenticates" "$([ "$code" = 200 ] && echo 1)" "HTTP $code"

CLI="$WORK/patchloop"
if (cd "$ROOT/cli" && go build -o "$CLI" ./cmd/patchloop) >"$WORK/cli-build.log" 2>&1; then
  rec "build CLI" PASS ""
  export PATCHLOOP_CONFIG="$WORK/cli/config.json"
  "$CLI" login --token "$TOKEN" --api "$BACKEND_URL" >"$WORK/cli-login.log" 2>&1
  ok "patchloop login --token" "$([ $? = 0 ] && echo 1)" "$(tr '\n' ' ' <"$WORK/cli-login.log" | sed "s/$EMAIL/<email>/g" | head -c 120)"
  "$CLI" whoami >"$WORK/cli-who.log" 2>&1; ok "patchloop whoami" "$([ $? = 0 ] && echo 1)"
  T2="$(now)"
  NO_COLOR=1 "$CLI" fix "$EASY_BUG" >"$WORK/cli-fix.log" 2>&1; rc=$?
  FIX_MS="$(python3 -c "import time; print(int((time.time()-$T2)*1000))")"
  ok "patchloop fix $EASY_BUG exits 0 (solved)" "$([ $rc = 0 ] && grep -q SOLVED "$WORK/cli-fix.log" && echo 1)" "exit $rc in ${FIX_MS}ms; $(grep -m1 SOLVED "$WORK/cli-fix.log")"
  NO_COLOR=1 "$CLI" fix "$EASY_BUG" --json >"$WORK/cli-json.log" 2>/dev/null; rc=$?
  ok "patchloop fix --json prints raw events ending in end" "$([ $rc = 0 ] && tail -n1 "$WORK/cli-json.log" | grep -q '"end"' && echo 1)" "exit $rc, $(wc -l <"$WORK/cli-json.log" | tr -d ' ') lines"
  "$CLI" runs >"$WORK/cli-runs.log" 2>&1; ok "patchloop runs" "$([ $? = 0 ] && grep -q "$EASY_BUG" "$WORK/cli-runs.log" && echo 1)"
  ok "CLI config is isolated (PATCHLOOP_CONFIG) and mode 0600" \
    "$([ -f "$PATCHLOOP_CONFIG" ] && [ "$(python3 -c "import os,stat,sys;print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode)))" "$PATCHLOOP_CONFIG")" = 0o600 ] && echo 1)"
else
  rec "build CLI" FAIL "$(tail -n 3 "$WORK/cli-build.log" | tr '\n' ' ')"
fi

# ------------------------------------------------------------------ guest (/try)
code="$(C -o "$WORK/dbugs.json" -w '%{http_code}' "$BACKEND_URL/api/demo/bugs")"
ok "guest GET /api/demo/bugs" "$([ "$code" = 200 ] && echo 1)" "HTTP $code"
code="$(C -o /dev/null -w '%{http_code}' "$BACKEND_URL/api/demo/runs/$RUN_ID/events")"
ok "guest cannot stream a user's run (404)" "$([ "$code" = 404 ] && echo 1)" "HTTP $code"
GUEST_OK=0; GUEST_429=""; FIRST_GUEST=""
for i in 1 2 3 4; do
  code="$(C -D "$WORK/g$i.h" -o "$WORK/g$i.json" -w '%{http_code}' "${jh[@]}" -X POST "$BACKEND_URL/api/demo/runs" -d "{\"bugId\":\"$HARD_BUG\"}")"
  if [ "$code" = 201 ]; then
    GUEST_OK=$((GUEST_OK + 1)); [ -z "$FIRST_GUEST" ] && FIRST_GUEST="$(json "$WORK/g$i.json" 'd["runId"]')" && T3="$(now)"
  elif [ "$code" = 429 ]; then GUEST_429="$i"; break
  else rec "guest POST /api/demo/runs #$i" FAIL "HTTP $code"; break; fi
done
RETRY="$( [ -n "$GUEST_429" ] && grep -i '^retry-after:' "$WORK/g$GUEST_429.h" | tr -d '\r' | cut -d' ' -f2)"
if [ "$GUEST_OK" = 3 ] && [ "$GUEST_429" = 4 ]; then
  rec "guest: 3 runs OK, 4th -> 429 + Retry-After" "$([ -n "$RETRY" ] && echo PASS || echo FAIL)" "Retry-After=${RETRY}s, error=$(json "$WORK/g4.json" 'd["error"]')"
elif [ -n "$GUEST_429" ] && [ "$GUEST_OK" -lt 3 ]; then
  rec "guest: 3 runs OK, 4th -> 429 + Retry-After" SKIP "$GUEST_OK OK then 429: this IP already used guest runs this hour (restart the backend to reset the in-memory bucket)"
else
  rec "guest: 3 runs OK, 4th -> 429 + Retry-After" FAIL "$GUEST_OK OK, 429 at #${GUEST_429:-never}"
fi
if [ -n "$FIRST_GUEST" ]; then
  python3 "$ROOT/scripts/e2e/sse_probe.py" --prefix "guest SSE" --t0 "$T3" \
    --backend-events "$BACKEND_URL/api/demo/runs/$FIRST_GUEST/events" >"$WORK/gprobe.tsv"
  grep -v '^METRIC' "$WORK/gprobe.tsv" | grep -E 'SSE through|first|last|done present|CONTRACT' >>"$RESULTS"
fi

# ------------------------------------------------------------------ report
echo
python3 - "$RESULTS" "$METRICS" <<'PY'
import sys
rows = [l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip()]
w = max(len(r[0]) for r in rows)
print(f"{'CHECK'.ljust(w)}  RESULT  DETAIL")
print("-" * (w + 40))
for r in rows:
    print(f"{r[0].ljust(w)}  {r[1].ljust(6)}  {r[2] if len(r) > 2 else ''}")
counts = {k: sum(1 for r in rows if r[1] == k) for k in ("PASS", "FAIL", "SKIP")}
print("-" * (w + 40))
print(f"{counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['SKIP']} SKIP")
m = [l.rstrip("\n").split("\t") for l in open(sys.argv[2]) if l.strip()]
if m:
    print("\nLatency (hard run, fake mode, through the backend):")
    names = {"ttfn_ms_client": "time to first node, client (POST -> node via backend SSE)",
             "ttfn_ms_agent": "time to first node, agent-reported",
             "run_latency_ms": "run latency, agent-reported",
             "end_ms_client": "POST -> end event, client",
             "relay_p50_ms": "backend relay overhead p50",
             "relay_max_ms": "backend relay overhead max"}
    for k, v in m:
        print(f"  {names.get(k, k)}: {float(v):.1f} ms")
sys.exit(1 if counts["FAIL"] else 0)
PY
