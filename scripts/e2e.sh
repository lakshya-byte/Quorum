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

# wait_merge_allowed RUN_ID: poll the PR gate until the (fake) checks are green, up to 30 s.
wait_merge_allowed() {
  for _ in $(seq 1 60); do
    C "${cj[@]}" -o "$WORK/wma.json" "$BACKEND_URL/api/runs/$1/pr"
    [ "$(json "$WORK/wma.json" 'd["mergeAllowed"]')" = true ] && return 0; sleep 0.5
  done
  return 1
}
# ================================================================== REPO FLOW (GitHub demo account, Slack fake API, CLI)
echo "repo flow ..."
SLACK_URL="${SLACK_API_BASE:-http://localhost:19090}"
SLACKDEV="$ROOT/.logs/bin/slackdev"
[ -x "$SLACKDEV" ] || SLACKDEV="$WORK/slackdev"
[ -x "$SLACKDEV" ] || (cd "$ROOT/backend" && go build -o "$SLACKDEV" ./cmd/slackdev) >"$WORK/slackdev-build.log" 2>&1
HAVE_SLACK=0; [ "$(C -o /dev/null -w '%{http_code}' "$SLACK_URL/_messages")" = 200 ] && [ -x "$SLACKDEV" ] && [ -n "${SLACK_SIGNING_SECRET:-}" ] && HAVE_SLACK=1
HAVE_GHWH=0; [ -n "${GITHUB_WEBHOOK_SECRET:-}" ] && HAVE_GHWH=1

# --- users without GitHub cannot start tasks
E2="e2e-nogh-$(date +%s)-$$@example.com"; J2="$WORK/cookies2.txt"
C -o /dev/null "${jh[@]}" -X POST "$BACKEND_URL/api/auth/signup" -d "{\"email\":\"$E2\",\"password\":\"$PASSWORD\",\"companyName\":\"E2E2\"}"
C -o "$WORK/otp2.json" -H "X-Agent-Secret: $AGENT_SHARED_SECRET" "$BACKEND_URL/internal/dev/otp?email=$E2"
C -o /dev/null -c "$J2" "${jh[@]}" -X POST "$BACKEND_URL/api/auth/verify-otp" -d "{\"email\":\"$E2\",\"code\":\"$(json "$WORK/otp2.json" 'd["code"]')\"}"
code="$(C -b "$J2" -o "$WORK/nogh.json" -w '%{http_code}' "${jh[@]}" -X POST "$BACKEND_URL/api/tasks" -d '{"repo":"demo/shop-api","task":"x"}')"
ok "POST /api/tasks before connecting GitHub -> 409 'connect github first'" "$([ "$code" = 409 ] && grep -qi 'connect github' "$WORK/nogh.json" && echo 1)" "HTTP $code $(json "$WORK/nogh.json" 'd["error"]')"
code="$(C -b "$J2" -o /dev/null -w '%{http_code}' "$BACKEND_URL/api/github/repos")"
ok "GET /api/github/repos before connecting -> 409" "$([ "$code" = 409 ] && echo 1)" "HTTP $code"

# --- GitHub: demo connect, repos, branches
req "GitHub: POST /api/github/demo (connect demo account)" 200 "$WORK/gh-demo.json" "${cj[@]}" -X POST "$BACKEND_URL/api/github/demo"
req "GitHub: GET /api/github/status" 200 "$WORK/gh-status.json" "${cj[@]}" "$BACKEND_URL/api/github/status"
ok "GitHub status: connected, mode demo, appConfigured false, 3 repos" "$([ "$(json "$WORK/gh-status.json" 'd["connected"]')" = true ] && [ "$(json "$WORK/gh-status.json" 'd["mode"]')" = demo ] && [ "$(json "$WORK/gh-status.json" 'd["repoCount"]')" = 3 ] && echo 1)" "$(head -c 200 "$WORK/gh-status.json")"
INSTALL_ID="$(json "$WORK/gh-status.json" 'd["installationId"]')"
req "GitHub: GET /api/github/repos" 200 "$WORK/gh-repos.json" "${cj[@]}" "$BACKEND_URL/api/github/repos"
ok "demo repos are exactly the agent's: shop-api, wordstats, booking" "$([ "$(json "$WORK/gh-repos.json" 'sorted(r["fullName"] for r in d)')" = '["demo/booking", "demo/shop-api", "demo/wordstats"]' ] && echo 1)" "$(json "$WORK/gh-repos.json" '[r["fullName"] for r in d]')"
req "GitHub: GET /api/github/repos?q=coupon (search)" 200 "$WORK/gh-repos-q.json" "${cj[@]}" "$BACKEND_URL/api/github/repos?q=coupon"
ok "repo search narrows to demo/shop-api" "$([ "$(json "$WORK/gh-repos-q.json" '[r["fullName"] for r in d]')" = '["demo/shop-api"]' ] && echo 1)"
req "GitHub: GET branches of demo/shop-api" 200 "$WORK/gh-br.json" "${cj[@]}" "$BACKEND_URL/api/github/repos/demo/shop-api/branches"
ok "branches: main is default" "$([ "$(json "$WORK/gh-br.json" 'd[0]["name"]+str(d[0]["default"])')" = mainTrue ] && echo 1)"
code="$(C -o /dev/null -w '%{http_code}' "$BACKEND_URL/api/github/callback?installation_id=1&setup_action=install&state=forged")"
ok "GitHub callback with a forged state is rejected (redirect with error, never a 5xx)" "$([ "$code" = 302 ] || [ "$code" = 303 ] && echo 1)" "HTTP $code"
code="$(C -o "$WORK/gh-conn.json" -w '%{http_code}' "${cj[@]}" "$BACKEND_URL/api/github/connect")"
ok "GitHub App connect without App credentials -> 503 'github app not configured'" "$([ "$code" = 503 ] && echo 1)" "HTTP $code $(json "$WORK/gh-conn.json" 'd["error"]')"

# --- create a task and stream it
echo "  creating task (demo/shop-api) ..."
code="$(C -b "$JAR" -o "$WORK/t-bad.json" -w '%{http_code}' "${jh[@]}" -X POST "$BACKEND_URL/api/tasks" -d '{"repo":"not a repo","task":"x"}')"
ok "POST /api/tasks with an invalid repo name -> 400 {error,code}" "$([ "$code" = 400 ] && [ -n "$(json "$WORK/t-bad.json" 'd["code"]')" ] && echo 1)" "HTTP $code"
TASK='Checkout totals are wrong when a percentage coupon is used: the discount also reduces shipping and rounds down.'
T0="$(now)"
req "POST /api/tasks (demo/shop-api)" 201 "$WORK/task.json" "${cj[@]}" "${jh[@]}" -X POST "$BACKEND_URL/api/tasks" \
  -d "{\"repo\":\"demo/shop-api\",\"branch\":\"main\",\"task\":\"$TASK\",\"autoPr\":true}"
TASK_RUN="$(json "$WORK/task.json" 'd["runId"]')"
python3 "$ROOT/scripts/e2e/repo_sse.py" --url "$BACKEND_URL/api/runs/$TASK_RUN/events" --cookie-jar "$JAR" --t0 "$T0" --out "$WORK/sse1.json"
S1="$WORK/sse1.json"
ok "SSE through the backend streams to 'end' (text/event-stream)" "$([ -z "$(json "$S1" 'd["error"]')" ] && [ "$(json "$S1" 'd["types"][-1]')" = end ] && case "$(json "$S1" 'd["content_type"]')" in text/event-stream*) echo 1;; esac)" "$(json "$S1" 'len(d["types"])') events, error=$(json "$S1" 'd["error"]')"
ok "events in order: repo < locate < repro < node < done < pr" "$([ "$(json "$S1" '(lambda t: t.index("repo")<t.index("locate")<t.index("repro")<t.index("node")<t.index("done")<t.index("pr"))(d["types"])')" = true ] && echo 1)" "$(json "$S1" '" ".join(dict.fromkeys(d["types"]))')"
ok "repo event: demo/shop-api, python, test command" "$([ "$(json "$S1" 'd["repo"]["full_name"]')" = demo/shop-api ] && [ "$(json "$S1" 'd["repo"]["language"]')" = python ] && [ -n "$(json "$S1" 'd["repo"]["test_command"]')" ] && echo 1)" "files=$(json "$S1" 'd["repo"]["files"]')"
ok "locate event lists a 2-file fix (cart.py + coupons.py)" "$([ "$(json "$S1" 'sorted(f["path"] for f in d["locate"]["files"])')" = '["shop/cart.py", "shop/coupons.py"]' ] && echo 1)"
ok "repro event: reproducer fails on the original code" "$([ "$(json "$S1" 'd["repro"]["failed_on_original"]')" = true ] && echo 1)" "$(json "$S1" 'd["repro"]["test_name"]')"
ok "node events carry multi-file 'files' and unified 'diff'" "$([ "$(json "$S1" 'd["nodes_with_files"]')" -ge 1 ] 2>/dev/null && [ "$(json "$S1" 'd["nodes_with_diff"]')" -ge 1 ] 2>/dev/null && echo 1)" "$(json "$S1" 'd["nodes"]') nodes, $(json "$S1" 'd["nodes_with_files"]') with files, $(json "$S1" 'd["nodes_with_diff"]') with diff"
ok "done: solved, best is a node object with 2 files" "$([ "$(json "$S1" 'd["done"]["solved"]')" = true ] && [ "$(json "$S1" 'len(d["best_files"])')" = 2 ] && echo 1)" "best files: $(json "$S1" 'd["best_files"]')"
ok "pr event: fake PR on a patchloop/ branch (no merge)" "$([ "$(json "$S1" 'd["pr"]["fake"]')" = true ] && case "$(json "$S1" 'd["pr"]["branch"]')" in patchloop/*) echo 1;; esac)" "$(json "$S1" 'd["pr"]["url"]')"
FIRST_MS="$(json "$S1" 'd["first_event_ms"]')"
rec "first SSE event latency (POST /api/tasks -> first event, client)" PASS "${FIRST_MS} ms (first event: $(json "$S1" 'd["first_type"]'))"
printf 'first_event_ms\t%s\n' "$FIRST_MS" >>"$METRICS"
PR_URL="$(json "$S1" 'd["pr"]["url"]')"; PR_NUM="$(json "$S1" 'd["pr"]["number"]')"; PR_BRANCH="$(json "$S1" 'd["pr"]["branch"]')"

STATUS=""
for _ in $(seq 1 40); do
  C "${cj[@]}" -o "$WORK/rrun.json" "$BACKEND_URL/api/runs/$TASK_RUN"
  STATUS="$(json "$WORK/rrun.json" 'd["status"]')"; [ "$STATUS" = completed ] && break; sleep 0.25
done
R="$WORK/rrun.json"
ok "run saved: kind repo, solved, prUrl/prNumber/prBranch match the pr event" "$([ "$STATUS" = completed ] && [ "$(json "$R" 'd["kind"]')" = repo ] && [ "$(json "$R" 'd["solved"]')" = true ] && [ "$(json "$R" 'd["prUrl"]')" = "$PR_URL" ] && [ "$(json "$R" 'd["prNumber"]')" = "$PR_NUM" ] && [ "$(json "$R" 'd["prBranch"]')" = "$PR_BRANCH" ] && echo 1)" "status=$STATUS"
ok "run.filesChanged is a number (2)" "$([ "$(json "$R" 'd["filesChanged"]')" = 2 ] && echo 1)" "filesChanged=$(json "$R" 'd["filesChanged"]')"
ok "run nodes keep files + diff; best node id set" "$([ "$(json "$R" 'sum(1 for n in d["nodes"] if n.get("files") and n.get("diff"))')" -ge 1 ] 2>/dev/null && [ -n "$(json "$R" 'd["bestNodeId"]')" ] && echo 1)"
ok "run.safety has guard/policy/security; cost.tokens > 0; traceId set" "$([ -n "$(json "$R" 'd["safety"]["guard"]')" ] && [ -n "$(json "$R" 'd["safety"]["policy"]')" ] && [ -n "$(json "$R" 'd["safety"]["security"]')" ] && [ "$(json "$R" 'd["cost"]["tokens"]')" -gt 0 ] 2>/dev/null && [ -n "$(json "$R" 'd["traceId"]')" ] && echo 1)" "tokens=$(json "$R" 'd["cost"]["tokens"]') trace=$(json "$R" 'd["traceId"]')"
ok "run has source web, repo, branch, task, no slackSent yet" "$([ "$(json "$R" 'd["source"]')" = web ] && [ "$(json "$R" 'd["repo"]')" = demo/shop-api ] && [ "$(json "$R" 'd["slackSent"]')" = false ] && echo 1)"
TRACE1="$(json "$R" 'd["traceId"]')"
ok "trace id propagated backend -> agent -> callback (same id in both logs)" "$([ -n "$TRACE1" ] && grep -q "$TRACE1" "$ROOT/.logs/backend.log" && grep -q "$TRACE1" "$ROOT/.logs/agent.log" && echo 1)" "$TRACE1"

# --- PR status and the merge gate (demo CI is pending for a few seconds after the run)
req "GET /api/runs/:id/pr" 200 "$WORK/pr1.json" "${cj[@]}" "$BACKEND_URL/api/runs/$TASK_RUN/pr"
ok "PR info: open, mergeable, checks pending -> mergeAllowed false with a reason" "$([ "$(json "$WORK/pr1.json" 'd["state"]')" = open ] && [ "$(json "$WORK/pr1.json" 'd["checks"]["state"]')" = pending ] && [ "$(json "$WORK/pr1.json" 'd["mergeAllowed"]')" = false ] && [ -n "$(json "$WORK/pr1.json" 'd["reason"]')" ] && echo 1)" "reason: $(json "$WORK/pr1.json" 'd["reason"]')"
code="$(C "${cj[@]}" -o "$WORK/merge0.json" -w '%{http_code}' "${jh[@]}" -X POST "$BACKEND_URL/api/runs/$TASK_RUN/merge" -d '{}')"
ok "POST merge while checks pending -> 409 with reason" "$([ "$code" = 409 ] && [ -n "$(json "$WORK/merge0.json" 'd["error"]')" ] && echo 1)" "HTTP $code: $(json "$WORK/merge0.json" 'd["error"]')"
code="$(C -o /dev/null -w '%{http_code}' "${jh[@]}" -X POST "$BACKEND_URL/api/runs/$TASK_RUN/merge" -d '{}')"
ok "POST merge without login -> 401" "$([ "$code" = 401 ] && echo 1)" "HTTP $code"

# --- follow-up adds a commit to the SAME PR
T0="$(now)"
req "POST /api/runs/:id/followup" 201 "$WORK/fu.json" "${cj[@]}" "${jh[@]}" -X POST "$BACKEND_URL/api/runs/$TASK_RUN/followup" -d '{"message":"Also add a test for a coupon of 100 percent."}'
FU_RUN="$(json "$WORK/fu.json" 'd["runId"]')"
python3 "$ROOT/scripts/e2e/repo_sse.py" --url "$BACKEND_URL/api/runs/$FU_RUN/events" --cookie-jar "$JAR" --t0 "$T0" --out "$WORK/sse2.json"
S2="$WORK/sse2.json"
ok "follow-up stream: pr event has updated:true on the same PR number/branch" "$([ "$(json "$S2" 'd["pr"]["updated"]')" = true ] && [ "$(json "$S2" 'd["pr"]["number"]')" = "$PR_NUM" ] && [ "$(json "$S2" 'd["pr"]["branch"]')" = "$PR_BRANCH" ] && echo 1)" "$(json "$S2" 'd["pr"]')"
for _ in $(seq 1 40); do C "${cj[@]}" -o "$WORK/frun.json" "$BACKEND_URL/api/runs/$FU_RUN"; [ "$(json "$WORK/frun.json" 'd["status"]')" = completed ] && break; sleep 0.25; done
ok "follow-up run: parentRunId set, same prNumber, solved" "$([ "$(json "$WORK/frun.json" 'd["parentRunId"]')" = "$TASK_RUN" ] && [ "$(json "$WORK/frun.json" 'd["prNumber"]')" = "$PR_NUM" ] && [ "$(json "$WORK/frun.json" 'd["solved"]')" = true ] && echo 1)"

# --- merge allowed once the (fake) checks have finished; merge as the user
ALLOWED=""
for _ in $(seq 1 30); do
  C "${cj[@]}" -o "$WORK/pr2.json" "$BACKEND_URL/api/runs/$FU_RUN/pr"
  [ "$(json "$WORK/pr2.json" 'd["mergeAllowed"]')" = true ] && { ALLOWED=1; break; }; sleep 0.5
done
ok "PR info on the follow-up run: checks success -> mergeAllowed true" "$ALLOWED" "checks=$(json "$WORK/pr2.json" 'd["checks"]["state"]')"
req "POST /api/runs/:id/merge (checks green)" 200 "$WORK/merge1.json" "${cj[@]}" "${jh[@]}" -X POST "$BACKEND_URL/api/runs/$FU_RUN/merge" -d '{"method":"squash"}'
ok "merge result: merged by the user, fake demo merge" "$([ "$(json "$WORK/merge1.json" 'd["merged"]')" = true ] && [ -n "$(json "$WORK/merge1.json" 'd["by"]')" ] && echo 1)" "by=$(json "$WORK/merge1.json" 'd["by"]') fake=$(json "$WORK/merge1.json" 'd.get("fake")')"
C "${cj[@]}" -o "$WORK/pr3.json" "$BACKEND_URL/api/runs/$FU_RUN/pr"
C "${cj[@]}" -o "$WORK/frun2.json" "$BACKEND_URL/api/runs/$FU_RUN"
ok "after merge: PR state merged, run.merged.by recorded" "$([ "$(json "$WORK/pr3.json" 'd["state"]')" = merged ] && [ -n "$(json "$WORK/frun2.json" 'd["merged"]["by"]')" ] && echo 1)"
C "${cj[@]}" -o "$WORK/pr-parent.json" "$BACKEND_URL/api/runs/$TASK_RUN/pr"
ok "merging the follow-up run also marks the original run's PR merged (same PR)" "$([ "$(json "$WORK/pr-parent.json" 'd["state"]')" = merged ] && echo 1)" "parent PR state=$(json "$WORK/pr-parent.json" 'd["state"]')"
code="$(C "${cj[@]}" -o /dev/null -w '%{http_code}' "${jh[@]}" -X POST "$BACKEND_URL/api/runs/$FU_RUN/merge" -d '{}')"
ok "merging twice is refused (409)" "$([ "$code" = 409 ] && echo 1)" "HTTP $code"
code="$(C -b "$J2" -o /dev/null -w '%{http_code}' "$BACKEND_URL/api/runs/$TASK_RUN/pr")"
ok "another user cannot read this run's PR (404)" "$([ "$code" = 404 ] && echo 1)" "HTTP $code"

# --- signed GitHub webhook (issues labeled patchloop)
if [ "$HAVE_GHWH" = 1 ] && [ -n "$INSTALL_ID" ] && [ "$INSTALL_ID" != 0 ]; then
  ghsign() { python3 -c 'import hmac,hashlib,sys; print("sha256="+hmac.new(sys.argv[1].encode(), open(sys.argv[2],"rb").read(), hashlib.sha256).hexdigest())' "$1" "$2"; }
  cat >"$WORK/wh.json" <<EOF
{"action":"labeled","installation":{"id":$INSTALL_ID},"sender":{"login":"octo-owner","type":"User"},
 "repository":{"full_name":"demo/wordstats"},"label":{"name":"patchloop"},
 "issue":{"number":17,"title":"Word counts are wrong","body":"'The' and 'the' are counted separately and don't is split in two."}}
EOF
  DELIVERY="e2e-delivery-$$-$(date +%s)"
  whpost() { # $1 secret $2 delivery -> prints status, body in $WORK/wh-out.json
    C -o "$WORK/wh-out.json" -w '%{http_code}' -X POST "$BACKEND_URL/api/github/webhook" -H 'Content-Type: application/json' \
      -H 'X-GitHub-Event: issues' -H "X-GitHub-Delivery: $2" -H "X-Hub-Signature-256: $(ghsign "$1" "$WORK/wh.json")" --data-binary @"$WORK/wh.json"
  }
  code="$(whpost wrong-secret "$DELIVERY-bad")"
  ok "GitHub webhook: bad signature rejected (401)" "$([ "$code" = 401 ] && echo 1)" "HTTP $code"
  code="$(C -o /dev/null -w '%{http_code}' -X POST "$BACKEND_URL/api/github/webhook" -H 'X-GitHub-Event: issues' --data-binary @"$WORK/wh.json")"
  ok "GitHub webhook: missing signature rejected (401)" "$([ "$code" = 401 ] && echo 1)" "HTTP $code"
  C "${cj[@]}" -o "$WORK/runs-before.json" "$BACKEND_URL/api/runs"
  code="$(whpost "$GITHUB_WEBHOOK_SECRET" "$DELIVERY")"
  ok "GitHub webhook: signed 'issues labeled patchloop' accepted (202)" "$([ "$code" = 202 ] && grep -q accepted "$WORK/wh-out.json" && echo 1)" "HTTP $code $(head -c 80 "$WORK/wh-out.json")"
  code="$(whpost "$GITHUB_WEBHOOK_SECRET" "$DELIVERY")"
  ok "GitHub webhook: replay of the same delivery is deduped" "$([ "$code" = 202 ] && grep -q duplicate "$WORK/wh-out.json" && echo 1)" "HTTP $code $(head -c 80 "$WORK/wh-out.json")"
  WH_RUN=""
  for _ in $(seq 1 40); do
    C "${cj[@]}" -o "$WORK/runs-after.json" "$BACKEND_URL/api/runs"
    WH_RUN="$(json "$WORK/runs-after.json" "next((r['id'] for r in d if r.get('source')=='github'), '')")"; [ -n "$WH_RUN" ] && break; sleep 0.25
  done
  for _ in $(seq 1 60); do C "${cj[@]}" -o "$WORK/whrun.json" "$BACKEND_URL/api/runs/$WH_RUN"; [ "$(json "$WORK/whrun.json" 'd["status"]')" = completed ] && break; sleep 0.5; done
  ok "webhook started exactly one run (source github, issue #17, demo/wordstats) that solved and opened a PR" \
    "$([ "$(json "$WORK/runs-after.json" "sum(1 for r in d if r.get('source')=='github')")" = 1 ] && [ "$(json "$WORK/whrun.json" 'd["issue"]["number"]')" = 17 ] && [ "$(json "$WORK/whrun.json" 'd["repo"]')" = demo/wordstats ] && [ "$(json "$WORK/whrun.json" 'd["solved"]')" = true ] && [ -n "$(json "$WORK/whrun.json" 'd["prUrl"]')" ] && echo 1)" "run $WH_RUN"
  sed -i.bak 's/"patchloop"/"bug"/' "$WORK/wh.json"
  code="$(whpost "$GITHUB_WEBHOOK_SECRET" "$DELIVERY-other-label")"
  ok "GitHub webhook: other labels are ignored" "$([ "$code" = 202 ] && grep -q ignored "$WORK/wh-out.json" && echo 1)" "$(head -c 80 "$WORK/wh-out.json")"
else
  rec "GitHub webhook checks" SKIP "GITHUB_WEBHOOK_SECRET not set or no demo installation id (start with scripts/dev-up.sh)"
fi

# --- Slack: link, /patchloop fix with threaded updates, Merge button
if [ "$HAVE_SLACK" = 1 ]; then
  SU="U$(date +%s)E2E"; SCH="C-E2E-$$"
  req "Slack: POST /api/slack/link-code" 201 "$WORK/link.json" "${cj[@]}" -X POST "$BACKEND_URL/api/slack/link-code"
  LINK="$(json "$WORK/link.json" 'd["code"]')"
  "$SLACKDEV" command -url "$BACKEND_URL" -secret "$SLACK_SIGNING_SECRET" -user "$SU" -channel "$SCH" "fix something" >"$WORK/sl-unlinked.txt" 2>&1
  ok "Slack: unlinked user gets link instructions (ephemeral), no run" "$(grep -q '^200' "$WORK/sl-unlinked.txt" && grep -qi 'link' "$WORK/sl-unlinked.txt" && echo 1)" "$(head -c 120 "$WORK/sl-unlinked.txt")"
  "$SLACKDEV" command -url "$BACKEND_URL" -secret "$SLACK_SIGNING_SECRET" -user "$SU" -channel "$SCH" "link $LINK" >"$WORK/sl-link.txt" 2>&1
  ok "Slack: /patchloop link <code> links the Slack user" "$(grep -q '^200' "$WORK/sl-link.txt" && grep -qi 'linked' "$WORK/sl-link.txt" && echo 1)" "$(head -c 120 "$WORK/sl-link.txt")"
  code="$(C -o /dev/null -w '%{http_code}' -X POST "$BACKEND_URL/slack/commands" -H 'X-Slack-Request-Timestamp: 1' -H 'X-Slack-Signature: v0=00' -d 'command=/patchloop&text=help')"
  ok "Slack: bad signature / stale timestamp rejected (401)" "$([ "$code" = 401 ] && echo 1)" "HTTP $code"
  "$SLACKDEV" command -url "$BACKEND_URL" -secret "$SLACK_SIGNING_SECRET" -user "$SU" -channel "$SCH" "fix Booking back-to-back reservations are rejected as conflicts repo:demo/booking" >"$WORK/sl-fix.txt" 2>&1
  ok "Slack: /patchloop fix acks within the 3 s window (200, ephemeral)" "$(grep -q '^200' "$WORK/sl-fix.txt" && echo 1)" "$(head -c 140 "$WORK/sl-fix.txt")"
  FINAL=""
  for _ in $(seq 1 80); do
    C -o "$WORK/slack-msgs.json" "$SLACK_URL/_messages"
    FINAL="$(json "$WORK/slack-msgs.json" "next((m['ts'] for m in d if m['channel']=='$SCH' and 'pl_merge' in json.dumps(m.get('blocks'))), '')")"
    [ -n "$FINAL" ] && break; sleep 0.5
  done
  python3 - "$WORK/slack-msgs.json" "$SCH" >"$WORK/slack-summary.json" <<'PY'
import json, sys
msgs = [m for m in json.load(open(sys.argv[1])) if m["channel"] == sys.argv[2] and m["method"] == "chat.postMessage"]
root = next((m for m in msgs if not m["threadTs"]), None)
threaded = [m for m in msgs if root and m["threadTs"] == root["ts"]]
final = next((m for m in msgs if "pl_merge" in json.dumps(m.get("blocks"))), None)
blocks = json.dumps(final.get("blocks")) if final else ""
print(json.dumps({"root": bool(root), "root_ts": root["ts"] if root else "", "threaded": len(threaded),
                  "final_in_thread": bool(final and root and (final["threadTs"] == root["ts"] or final["ts"] == root["ts"])),
                  "has_merge": "pl_merge" in blocks, "has_review": "Review" in blocks, "has_changes": "pl_changes" in blocks,
                  "final_text": (final or {}).get("text", "")[:120]}))
PY
  SS="$WORK/slack-summary.json"
  ok "Slack: root message + threaded updates (>= 3 in the thread)" "$([ "$(json "$SS" 'd["root"]')" = true ] && [ "$(json "$SS" 'd["threaded"]')" -ge 3 ] 2>/dev/null && echo 1)" "threaded=$(json "$SS" 'd["threaded"]')"
  ok "Slack: final Block Kit message has Review, Merge and Ask for changes buttons" "$([ "$(json "$SS" 'd["has_merge"]')" = true ] && [ "$(json "$SS" 'd["has_review"]')" = true ] && [ "$(json "$SS" 'd["has_changes"]')" = true ] && echo 1)" "$(json "$SS" 'd["final_text"]')"
  C "${cj[@]}" -o "$WORK/runs-sl.json" "$BACKEND_URL/api/runs"
  SL_RUN="$(json "$WORK/runs-sl.json" "next((r['id'] for r in d if r.get('source')=='slack'), '')")"
  ok "Slack: run recorded with source slack, repo demo/booking, slack thread ref" "$([ -n "$SL_RUN" ] && [ "$(json "$WORK/runs-sl.json" "next(r['repo'] for r in d if r['id']=='$SL_RUN')")" = demo/booking ] && [ -n "$(json "$WORK/runs-sl.json" "next(r['slack']['threadTs'] for r in d if r['id']=='$SL_RUN')")" ] && echo 1)"
  ROOT_TS="$(json "$SS" 'd["root_ts"]')"
  # Merge button right away: the fake CI is still pending, so it is refused in the thread.
  "$SLACKDEV" interact -url "$BACKEND_URL" -secret "$SLACK_SIGNING_SECRET" -user "$SU" -channel "$SCH" -thread "$ROOT_TS" -action pl_merge -value "$SL_RUN" >"$WORK/sl-int1.txt" 2>&1
  ok "Slack: Merge button interaction acked (200)" "$(grep -q '^200' "$WORK/sl-int1.txt" && echo 1)" "$(head -c 80 "$WORK/sl-int1.txt")"
  wait_merge_allowed "$SL_RUN"
  "$SLACKDEV" interact -url "$BACKEND_URL" -secret "$SLACK_SIGNING_SECRET" -user "$SU" -channel "$SCH" -thread "$ROOT_TS" -action pl_merge -value "$SL_RUN" >"$WORK/sl-int2.txt" 2>&1
  MERGED=""
  for _ in $(seq 1 30); do C "${cj[@]}" -o "$WORK/slrun.json" "$BACKEND_URL/api/runs/$SL_RUN"; [ -n "$(json "$WORK/slrun.json" 'd["merged"]["by"]')" ] && { MERGED=1; break; }; sleep 0.3; done
  ok "Slack: Merge button merges the PR after checks pass (run.merged set)" "$MERGED" "$(json "$WORK/slrun.json" 'd["merged"]')"
  C -o "$WORK/slack-msgs2.json" "$SLACK_URL/_messages"
  ok "Slack: merge result (refusal, then success) posted in the thread" "$([ "$(json "$WORK/slack-msgs2.json" "sum(1 for m in d if m['channel']=='$SCH' and m['threadTs']=='$ROOT_TS' and ('erge' in m['text']))")" -ge 2 ] 2>/dev/null && echo 1)" "$(json "$WORK/slack-msgs2.json" "[m['text'][:60] for m in d if m['channel']=='$SCH' and m['threadTs']=='$ROOT_TS'][-3:]")"
  C "${cj[@]}" -o "$WORK/slrun2.json" "$BACKEND_URL/api/runs/$SL_RUN"
  ok "Slack: run.slackSent is true (UI reads this, no extra event)" "$([ "$(json "$WORK/slrun2.json" 'd["slackSent"]')" = true ] && echo 1)" "slackSent=$(json "$WORK/slrun2.json" 'd["slackSent"]')"
  "$SLACKDEV" interact -url "$BACKEND_URL" -secret "$SLACK_SIGNING_SECRET" -user "U-STRANGER" -channel "$SCH" -thread "$ROOT_TS" -action pl_merge -value "$SL_RUN" >"$WORK/sl-int3.txt" 2>&1
  ok "Slack: an unlinked stranger cannot use the Merge button (acked, nothing merged by them)" "$(grep -q '^200' "$WORK/sl-int3.txt" && echo 1)"
else
  rec "Slack checks" SKIP "fake Slack API / SLACK_SIGNING_SECRET not available (scripts/dev-up.sh starts them)"
fi

# --- CLI against the live backend
if [ -x "$CLI" ]; then
  export NO_COLOR=1
  "$CLI" connect github --demo --no-open >"$WORK/cli-conn.log" 2>&1; ok "CLI: patchloop connect github --demo" "$([ $? = 0 ] && grep -qi demo "$WORK/cli-conn.log" && echo 1)" "$(tr '\n' ' ' <"$WORK/cli-conn.log" | head -c 100)"
  "$CLI" repos >"$WORK/cli-repos.log" 2>&1; ok "CLI: patchloop repos lists the 3 demo repos" "$([ $? = 0 ] && grep -q shop-api "$WORK/cli-repos.log" && grep -q wordstats "$WORK/cli-repos.log" && grep -q booking "$WORK/cli-repos.log" && echo 1)"
  "$CLI" fix --repo demo/wordstats "Word counts are wrong: The and the are counted separately and don't is split in two." >"$WORK/cli-rfix.out" 2>"$WORK/cli-rfix.err"; rc=$?
  CLI_PR="$(tail -n1 "$WORK/cli-rfix.out")"
  ok "CLI: patchloop fix --repo demo/wordstats exits 0, last stdout line is PR: <url>" "$([ $rc = 0 ] && case "$CLI_PR" in "PR: https://github.com/demo/wordstats/pull/"*) echo 1;; esac)" "exit $rc, $CLI_PR"
  ok "CLI: live view shows repo, locate, repro stages" "$(cat "$WORK/cli-rfix.out" "$WORK/cli-rfix.err" | grep -qi 'reproducer' && cat "$WORK/cli-rfix.out" "$WORK/cli-rfix.err" | grep -qi 'locate' && echo 1)"
  C "${cj[@]}" -o "$WORK/runs-cli.json" "$BACKEND_URL/api/runs"
  CLI_RUN="$(json "$WORK/runs-cli.json" "next((r['id'] for r in d if r.get('source')=='cli' and r.get('kind')=='repo'), '')")"
  ok "CLI: run recorded with source cli" "$([ -n "$CLI_RUN" ] && echo 1)" "$CLI_RUN"
  echo n | "$CLI" merge "$CLI_RUN" >"$WORK/cli-merge0.log" 2>&1; rc=$?
  ok "CLI: merge refused while checks are pending (exit 1, reason printed)" "$([ $rc = 1 ] && grep -qiE 'pending|still running' "$WORK/cli-merge0.log" && echo 1)" "exit $rc: $(tr '\n' ' ' <"$WORK/cli-merge0.log" | head -c 120)"
  "$CLI" changes "$CLI_RUN" "Also keep punctuation-only tokens out of the counts." >"$WORK/cli-chg.out" 2>"$WORK/cli-chg.err"; rc=$?
  ok "CLI: patchloop changes pushes a commit to the same PR (exit 0)" "$([ $rc = 0 ] && tail -n1 "$WORK/cli-chg.out" | grep -q "$(echo "$CLI_PR" | sed 's/^PR: //')" && echo 1)" "exit $rc, $(tail -n1 "$WORK/cli-chg.out")"
  wait_merge_allowed "$CLI_RUN"
  "$CLI" merge "$CLI_RUN" --yes >"$WORK/cli-merge1.log" 2>&1; rc=$?
  C "${cj[@]}" -o "$WORK/clirun.json" "$BACKEND_URL/api/runs/$CLI_RUN"
  ok "CLI: patchloop merge --yes merges once checks are green" "$([ $rc = 0 ] && [ -n "$(json "$WORK/clirun.json" 'd["merged"]["by"]')" ] && echo 1)" "exit $rc: $(tr '\n' ' ' <"$WORK/cli-merge1.log" | head -c 120)"
  "$CLI" doctor >"$WORK/cli-doctor.log" 2>&1; rc=$?; ok "CLI: patchloop doctor exits 0" "$([ $rc = 0 ] && echo 1)" "exit $rc"
  "$CLI" status >"$WORK/cli-status.log" 2>&1; rc=$?; ok "CLI: patchloop status shows github demo" "$([ $rc = 0 ] && grep -qi github "$WORK/cli-status.log" && echo 1)" "$(tr '\n' ' ' <"$WORK/cli-status.log" | head -c 140)"
  "$CLI" fix --repo demo/nope "x" >"$WORK/cli-bad.out" 2>"$WORK/cli-bad.err"; rc=$?
  ok "CLI: unknown demo repo exits 2 with a hint" "$([ $rc = 2 ] && echo 1)" "exit $rc: $(tr '\n' ' ' <"$WORK/cli-bad.err" | head -c 120)"
else
  rec "CLI repo flow" SKIP "CLI did not build"
fi

# --- notifications
req "GET /api/notifications" 200 "$WORK/notes.json" "${cj[@]}" "$BACKEND_URL/api/notifications"
ok "notifications: pr_opened, pr_updated and merged exist; unread counted" "$([ "$(json "$WORK/notes.json" 'sorted(set(n["kind"] for n in d["notifications"]) & {"pr_opened","pr_updated","merged"})')" = '["merged", "pr_opened", "pr_updated"]' ] && [ "$(json "$WORK/notes.json" 'd["unread"]')" -ge 3 ] 2>/dev/null && echo 1)" "kinds=$(json "$WORK/notes.json" 'sorted(set(n["kind"] for n in d["notifications"]))') unread=$(json "$WORK/notes.json" 'd["unread"]')"
NID="$(json "$WORK/notes.json" 'd["notifications"][0]["id"]')"
req "POST /api/notifications/:id/read" 200 "$WORK/noteread.json" "${cj[@]}" -X POST "$BACKEND_URL/api/notifications/$NID/read"

# --- callback auth + agent-side token handling
code="$(C -o /dev/null -w '%{http_code}' "${jh[@]}" -X POST "$BACKEND_URL/internal/runs/$AGENT_RUN/complete" -d '{}')"
ok "agent callback without X-Agent-Secret -> 401" "$([ "$code" = 401 ] && echo 1)" "HTTP $code"
code="$(C -o /dev/null -w '%{http_code}' "${jh[@]}" -H 'X-Agent-Secret: wrong' -X POST "$BACKEND_URL/internal/runs/$AGENT_RUN/complete" -d '{}')"
ok "agent callback with a wrong secret -> 401" "$([ "$code" = 401 ] && echo 1)" "HTTP $code"
SENTINEL="ghs_E2ESENTINEL$(python3 -c 'import secrets;print(secrets.token_hex(12))')"
if [ "$AGENT_DIRECT" = 1 ]; then
  C -o "$WORK/sent.json" -H "X-Agent-Secret: $AGENT_SHARED_SECRET" "${jh[@]}" -X POST "$AGENT_URL/repo-runs" \
    -d "{\"task\":\"Back-to-back bookings are rejected as conflicts.\",\"repo\":{\"full_name\":\"demo/booking\",\"branch\":\"main\"},\"github_token\":\"$SENTINEL\",\"auto_pr\":true,\"issue_ref\":3,\"source\":\"github\"}"
  SENT_RUN="$(json "$WORK/sent.json" 'd["run_id"]')"
  ok "agent /repo-runs accepts issue_ref as a plain integer and a per-run token" "$([ -n "$SENT_RUN" ] && echo 1)" "$(head -c 120 "$WORK/sent.json")"
  C -N --max-time 60 -H "X-Agent-Secret: $AGENT_SHARED_SECRET" "$AGENT_URL/runs/$SENT_RUN/events" >"$WORK/sent-sse.txt"
  C -H "X-Agent-Secret: $AGENT_SHARED_SECRET" -o "$WORK/sent-run.json" "$AGENT_URL/runs/$SENT_RUN"
  ok "per-run github_token never appears in agent events, run record or logs" "$(! grep -rq "$SENTINEL" "$WORK/sent-sse.txt" "$WORK/sent-run.json" "$ROOT/.logs/agent.log" "$ROOT/.logs/backend.log" "$ROOT/agent/runs" 2>/dev/null && echo 1)"
fi
# --- secrets must not be in any log
SECRETS=("$TOKEN" "$AGENT_SHARED_SECRET" "$JWT_ACCESS_SECRET" "$JWT_REFRESH_SECRET" "$TOKEN_ENC_KEY" "$GITHUB_WEBHOOK_SECRET" "$SLACK_SIGNING_SECRET" "$PASSWORD")
LEAK=0; LEAKED=""
for s in "${SECRETS[@]}"; do [ -n "$s" ] && grep -qF -- "$s" "$ROOT"/.logs/*.log 2>/dev/null && { LEAK=1; LEAKED="$LEAKED ${s:0:6}..."; }; done
grep -qE 'ghs_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gho_[A-Za-z0-9]{20,}|ghu_[A-Za-z0-9]{20,}' "$ROOT"/.logs/*.log 2>/dev/null && { LEAK=1; LEAKED="$LEAKED github-token-pattern"; }
ok "no token/secret/password appears in any .logs/*.log (GitHub token patterns, API token, shared secret, JWT, enc key, webhook/Slack secrets)" "$([ $LEAK = 0 ] && echo 1)" "${LEAKED:-clean}"

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
             "relay_max_ms": "backend relay overhead max",
             "first_event_ms": "first SSE event of a repo task (POST /api/tasks -> first event, client)"}
    for k, v in m:
        print(f"  {names.get(k, k)}: {float(v):.1f} ms")
sys.exit(1 if counts["FAIL"] else 0)
PY
