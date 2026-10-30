# PatchLoop setup

This page covers running the stack, creating the GitHub App and the Slack app, every environment
variable, the hosts that must be reachable, how to test each trigger, a three-minute demo and
troubleshooting.

Two modes exist and the UI labels them:

- **Demo / fake mode (no keys, no network):** fake model, local sandbox, a Demo GitHub account with three
  bundled Python repos (`demo/shop-api`, `demo/wordstats`, `demo/booking`), simulated pull requests and merges
  (labelled "demo PR"), and a fake Slack API. Everything in "Run it" and the demo script works here.
- **Live mode:** real GitHub App, real Slack app, Nebius models and sandboxes. The sections below
  describe what to create. These live paths are implemented against the official docs and covered by mock-based
  tests, but they have not been exercised against the real services in this repository's test runs.

## 1. Run it

Requirements: Go 1.27+ (or any Go with toolchain download), Node 22, Python 3.12+, and either Docker
or a MongoDB you can reach.

```bash
scripts/dev-up.sh            # Mongo, agent, fake Slack API, backend (DEV_MODE), frontend
FRONTEND_MODE=prod scripts/dev-up.sh   # same, with a production Next.js build (faster pages)
scripts/e2e.sh               # API, SSE, GitHub webhook, Slack, CLI end to end; PASS/FAIL table
node frontend/e2e/ui-real.cjs [dir]    # browser flow (needs Playwright + Chromium); screenshots at 1440 and 375
scripts/dev-down.sh          # stop everything (add --mongo to stop the pl-mongo container)
```

`dev-up.sh` needs MongoDB. If it cannot start one it prints three fixes:
1. start Docker Desktop (or the docker daemon) and run it again;
2. `export MONGO_URI='mongodb+srv://...'` (Atlas free tier). When `MONGO_URI` is set Docker is skipped;
3. `brew install mongodb-community && brew services start mongodb-community`.

It creates a Python venv in `.logs/venv` on the first run (or set `AGENT_VENV=/path/to/venv`), generates dev-only
secrets in `.logs/dev.env`, and prints the URLs:

| What | URL |
|---|---|
| Website | http://localhost:3000 |
| Backend API | http://localhost:8080 |
| Agent (internal, `X-Agent-Secret`) | http://localhost:8001 |
| Fake Slack API (`GET /_messages` shows what Slack would show) | http://localhost:19090 |

**Signing in without email (DEV_MODE):** sign up at `/signup`, then read the one-time code from the backend:

```bash
. .logs/dev.env
curl -s -H "X-Agent-Secret: $AGENT_SHARED_SECRET" "http://localhost:8080/internal/dev/otp?email=YOU@example.com"
```

`DEV_MODE=true` keeps OTPs in memory and exposes that route. Never set it in production.

Docker Compose is described in the root README.

## 2. Create the GitHub App (live GitHub)

PatchLoop uses a GitHub **App** (not an OAuth app with the `repo` scope, and not a personal access token): you
grant it only the repos you choose, and the agent never receives a user token.

GitHub, Settings, Developer settings, GitHub Apps, **New GitHub App**:

| Field | Value |
|---|---|
| GitHub App name | anything unique; its slug becomes `GITHUB_APP_SLUG` |
| Homepage URL | your `FRONTEND_URL` |
| Callback URL | `${PUBLIC_URL}/api/github/callback` |
| **Request user authorization (OAuth) during installation** | **checked** |
| Setup URL | `${PUBLIC_URL}/api/github/callback` (leave "Redirect on update" unchecked) |
| Webhook, Active | checked |
| Webhook URL | `${PUBLIC_URL}/api/github/webhook` |
| Webhook secret | a long random string; becomes `GITHUB_WEBHOOK_SECRET` |
| Expire user authorization tokens | on (the backend refreshes them) |
| Where can this GitHub App be installed | Only on this account (or Any account, your choice) |

Repository permissions:

| Permission | Access | Why |
|---|---|---|
| Contents | Read and write | read the repo, push the `patchloop/*` branch |
| Pull requests | Read and write | open the PR, read mergeability |
| Issues | Read and write | comment "PatchLoop is on it" on triggering issues |
| Checks | Read-only | show CI status and gate Merge |
| Commit statuses | Read-only | same, for status-based CI |
| Metadata | Read-only | mandatory |

Subscribe to events: **Issues**, **Issue comment**, **Pull request**, **Check suite** (the Installation event is
always delivered).

After creating it: note the **App ID** (`GITHUB_APP_ID`), generate a **private key** (`GITHUB_APP_PRIVATE_KEY`, the
PEM or its base64), and note the **Client ID** and a generated **client secret** (`GITHUB_CLIENT_ID`,
`GITHUB_CLIENT_SECRET`).

**Why "Request user authorization (OAuth) during installation" must be checked.** The callback
`GET /api/github/callback?installation_id&setup_action&code&state` requires the OAuth `code`. The backend uses it for
two things: (1) it exchanges the code for the installing user's token and lists that user's installations, which
**proves the `installation_id` in the URL really belongs to the signed-in user** (without this check anyone could
claim someone else's installation id); (2) it stores that user token (encrypted, AES-256-GCM) so that **Merge runs
with the user's own permission**, never with the App's. Without the checkbox GitHub sends no `code`, the
callback redirects to `${FRONTEND_URL}/integrations?github=error&reason=no_authorization`, and nothing is linked.
The agent only ever receives a short-lived installation token for the one run, and it has no merge function.

Locally you need a public URL for the webhook and callback (a tunnel such as `ngrok http 8080`); set `PUBLIC_URL` to it.

## 3. Create the Slack app (live Slack)

api.slack.com/apps, Create New App, **From an app manifest**, paste (replace `YOUR_PUBLIC_URL` with `PUBLIC_URL`):

```yaml
display_information:
  name: PatchLoop
  description: Fix a bug from Slack. Agents propose, tests decide, you merge.
features:
  bot_user:
    display_name: PatchLoop
    always_online: false
  slash_commands:
    - command: /patchloop
      url: https://YOUR_PUBLIC_URL/slack/commands
      description: Fix a bug, link your account, set a default repo
      usage_hint: fix <problem> [repo:owner/name] | link <code> | repo owner/name
      should_escape: false
oauth_config:
  scopes:
    bot:
      - commands
      - app_mentions:read
      - chat:write
      - channels:history
      - groups:history
settings:
  event_subscriptions:
    request_url: https://YOUR_PUBLIC_URL/slack/events
    bot_events:
      - app_mention
      - message.channels
      - message.groups
  interactivity:
    is_enabled: true
    request_url: https://YOUR_PUBLIC_URL/slack/interactions
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

Install the app to your workspace, then set `SLACK_SIGNING_SECRET` (Basic Information) and `SLACK_BOT_TOKEN`
(`xoxb-...`, OAuth & Permissions). Invite the bot to the channel (`/invite @PatchLoop`). Requests are verified with
`X-Slack-Signature` v0 and rejected when the timestamp is more than 5 minutes old.

Link your Slack user once: **Integrations, Slack, "Get link code"** on the website, then `/patchloop link <code>` in
Slack. A per-user incoming webhook (Integrations, Slack webhook) is a separate, simpler option that only posts a
completion message.

## 4. Environment variables

### Backend (`backend/.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | 8080 | listen port |
| `MONGO_URI`, `MONGO_DB_NAME` | `mongodb://localhost:27017`, `patchloop` | database |
| `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET` | required | session tokens |
| `AGENT_URL`, `AGENT_SHARED_SECRET` | `http://localhost:8001`, required | internal agent; same secret on both sides, also authenticates the completion callback |
| `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | required unless `DEV_MODE` | OTP email |
| `FRONTEND_ORIGIN`, `FRONTEND_URL` | `http://localhost:3000` | CORS origin; where the install flow redirects |
| `PUBLIC_URL` | `http://localhost:8080` | backend public base (callback and webhook URLs) |
| `PUBLIC_APP_URL` | `FRONTEND_ORIGIN` | base for links in Slack and PRs |
| `TOKEN_ENC_KEY` | none | base64 of 32 bytes (`openssl rand -base64 32`); encrypts GitHub tokens and Slack webhooks at rest. Unset with `DEV_MODE=true` derives a key; unset otherwise tokens cannot be stored |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY` | none | the GitHub App. Unset = only the Demo account works |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | none | the App's user authorization (merge as the user) |
| `GITHUB_WEBHOOK_SECRET` | none | HMAC secret for `/api/github/webhook`; unset = webhook answers 503 |
| `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN` | none | Slack app. Unset = Slack commands answer 503 |
| `SLACK_API_BASE` | `https://slack.com/api` | point at the fake Slack API for offline runs |
| `SLACK_WEBHOOK_URL` | none | optional global incoming webhook for completion messages |
| `TASKS_PER_USER_PER_HOUR` | 10 | repo tasks per user (web, CLI, Slack, GitHub share it) |
| `LIVE_RUNS_PER_USER_PER_DAY`, `GUEST_RUNS_PER_HOUR`, `TRUSTED_PROXIES` | 10, 3, empty | limits |
| `DEMO_CHECKS_PENDING_SEC` | 4 (dev-up.sh: 6) | how long the fake CI of demo PRs stays "pending"; Merge is refused meanwhile |
| `GITHUB_API_URL`, `GITHUB_WEB_URL` | github.com | test overrides / GitHub Enterprise |
| `COOKIE_SECURE`, `COOKIE_DOMAIN` | false, localhost | set for HTTPS |
| `NEW_RELIC_LICENSE_KEY`, `NEW_RELIC_APP_NAME` | none | optional APM |
| `DEV_MODE` | false | OTP route and relaxed secrets, tests and local use only |

### Agent (`agent/.env.example`)

| Variable | Purpose |
|---|---|
| `AGENT_SHARED_SECRET` | required; unset = every route except `/health` answers 401 |
| `BACKEND_CALLBACK_URL` | where to POST `/internal/runs/:id/complete` (header `X-Agent-Secret`, W3C `traceparent`) |
| `PORT`, `HOST` | listen address (keep it private) |
| `PATCHLOOP_MODE` | `fake` (default), `hybrid`, `live` |
| `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID`, `MODEL_NANO/SUPER/ULTRA` | live models and sandboxes |
| `GUARD_BACKEND`, `GUARD_FAIL_MODE`, `NVIDIA_API_KEY` | guardrails |
| `RUN_MAX_TOKENS`, `RUN_MAX_SECONDS`, `RUN_MAX_CANDIDATES` | per-run budgets |
| `ALLOW_LOCAL_REPO_EXEC` | allow running a real repo's tests on the agent host (off; real repos otherwise run only in Nebius sandboxes) |
| `GITHUB_TOKEN`, `GITHUB_REPO` | only for the legacy bundled-bug PR path |
| `LANGSMITH_API_KEY`, `NEW_RELIC_LICENSE_KEY` | optional tracing |
| `FAKE_DELAY_SCALE` | fake-mode pacing |

The per-run GitHub installation token arrives in the `/repo-runs` body (`github_token`) and is never logged,
persisted or emitted in events. For `demo/*` repos it is `null`.

### Frontend

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | backend URL, inlined at build time |
| `MOCK_PORT`, `MOCK_SPEED`, `MOCK_GITHUB_APP` | only for `npm run mock` (a no-backend mock server) |

### CLI

| Variable | Purpose |
|---|---|
| `PATCHLOOP_API` | backend URL for one command |
| `PATCHLOOP_CONFIG` | config file path (default `~/.config/patchloop/config.json`, mode 0600) |
| `NO_COLOR` | disable colours |

### dev-up.sh

`MONGO_URI`, `PATCHLOOP_MODE`, `FRONTEND_MODE=dev|prod`, `AGENT_VENV`, `MONGO_DB_NAME`, `FAKE_DELAY_SCALE`,
`DEMO_CHECKS_PENDING_SEC`, `SLACK_FAKE=0`.

## 5. Hosts that must be reachable

| Host | Used by |
|---|---|
| `api.github.com`, `github.com` | backend (App JWT, installation tokens, merge), agent (repo tarball, git data API) |
| `slack.com` (`slack.com/api`), `hooks.slack.com` | backend (bot messages; incoming webhooks) |
| `api.tokenfactory.nebius.com` (Nebius Token Factory; also `api.studio.nebius.com` if your account uses it) | agent models |
| Nebius Sandboxes API | agent, live mode |
| `api.smith.langchain.com` | agent, optional tracing |
| `collector.newrelic.com` | backend and agent, optional APM |
| `integrate.api.nvidia.com` | agent, optional NVIDIA guard |
| `api.resend.com` | backend OTP email |

Inbound: GitHub and Slack must reach `${PUBLIC_URL}/api/github/webhook`, `/api/github/callback`,
`/slack/commands`, `/slack/events`, `/slack/interactions`. The agent must not be public.

## 6. Test each trigger

All of these work offline with `scripts/dev-up.sh` (Demo account, fake Slack), and `scripts/e2e.sh` runs them for you.

**Website.** Sign in, Integrations, "Use demo account", Fix a bug, pick `demo/shop-api`, describe the bug, Start.
Watch the pipeline, review the diff, wait for "Checks passing", Merge.

**CLI.**
```bash
cd cli && go build -o /tmp/patchloop ./cmd/patchloop
/tmp/patchloop login --token plk_... --api http://localhost:8080    # token from /settings/tokens
/tmp/patchloop connect github --demo
/tmp/patchloop fix --repo demo/wordstats "Word counts are wrong: The and the are counted separately"
/tmp/patchloop merge <run-id>   /tmp/patchloop changes <run-id> "also handle empty input"
/tmp/patchloop doctor; /tmp/patchloop status
```

**Slack (offline, fake API).** With the dev stack running (`.logs/dev.env` has the secrets):
```bash
. .logs/dev.env
# website: Integrations, "Get link code", then:
.logs/bin/slackdev command -url http://localhost:8080 -secret $SLACK_SIGNING_SECRET -user U1 -channel C1 "link <code>"
.logs/bin/slackdev command -url http://localhost:8080 -secret $SLACK_SIGNING_SECRET -user U1 -channel C1 "fix back-to-back bookings are rejected repo:demo/booking"
curl -s localhost:19090/_messages | python3 -m json.tool        # threaded updates and the final buttons
.logs/bin/slackdev interact -url http://localhost:8080 -secret $SLACK_SIGNING_SECRET -user U1 -channel C1 -thread <root ts> -action pl_merge -value <run id>
```
Live: in a channel with the bot, `/patchloop fix <problem> repo:owner/name`, or mention `@PatchLoop` with a pasted alert;
use the Merge and Ask for changes buttons; reply in the thread to ask for changes.

**GitHub issue label.** Offline, send a signed webhook (this is what `e2e.sh` does):
```bash
. .logs/dev.env
INST=$(curl -s -b cookies http://localhost:8080/api/github/status | python3 -c 'import json,sys;print(json.load(sys.stdin)["installationId"])')
BODY='{"action":"labeled","installation":{"id":'$INST'},"sender":{"login":"o","type":"User"},"repository":{"full_name":"demo/wordstats"},"label":{"name":"patchloop"},"issue":{"number":17,"title":"Word counts are wrong","body":"The and the are counted separately"}}'
SIG=sha256=$(printf %s "$BODY" | openssl dgst -sha256 -hmac "$GITHUB_WEBHOOK_SECRET" | awk '{print $2}')
curl -s -X POST http://localhost:8080/api/github/webhook -H 'X-GitHub-Event: issues' -H "X-GitHub-Delivery: d1" -H "X-Hub-Signature-256: $SIG" -d "$BODY"
```
A bad signature gets 401; a replayed `X-GitHub-Delivery` is answered `duplicate`. Live: install the App on a repo,
add the label `patchloop` to an issue, or comment `@patchloop fix` (comments are only honoured from owners, members
and collaborators); comment `@patchloop <change>` on a `patchloop/*` PR to ask for changes.

## 7. Demo in three minutes (offline)

1. `FRONTEND_MODE=prod scripts/dev-up.sh` (about 20 s once built).
2. Open `/signup`, create an account, fetch the code with the DEV_MODE curl above.
3. Integrations, **Use demo account**. Optionally get a Slack link code.
4. Fix a bug, `demo/shop-api`, "Checkout totals are wrong when a percentage coupon is used". Narrate the stages:
   repo, locate (two files), reproducer that fails on the original code, three parallel attempts, the policy gate
   blocking one, the critic's lesson, the winner passing 13/13.
5. In the PR card point out "Checks running" and the disabled Merge with its reason, then the green check and click Merge.
   Say clearly: this is a demo PR, nothing real is merged, and no agent code can merge.
6. Ask for changes on a run (before merging): a second commit lands on the same PR.
7. Show the same from the terminal (`patchloop fix --repo demo/booking ...`) and the dashboard history (cost, speed, safety, trace id).

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `dev-up.sh`: MongoDB not available | follow the three printed fixes; or `MONGO_URI=...` |
| port 3000/8080/8001 in use | `scripts/dev-down.sh`, or stop the other process |
| `/new` says "Connect GitHub first" | Integrations, Use demo account (or install the App) |
| GitHub connect answers 503 "github app not configured" | set `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY` (or use the demo account) |
| Callback redirects with `reason=no_authorization` | the App's "Request user authorization (OAuth) during installation" is not checked |
| `reason=installation_not_yours` | the installation id in the URL is not one of the signed-in user's installations |
| `reason=invalid_state` | the install link expired (10 minutes) or belongs to another user; start again from Integrations |
| "that repository is not granted to the PatchLoop GitHub App" | add the repo to the installation on GitHub |
| Webhook 401 | wrong `GITHUB_WEBHOOK_SECRET`, or the body was altered by a proxy |
| Webhook 503 | `GITHUB_WEBHOOK_SECRET` not set |
| Slack 401 | wrong `SLACK_SIGNING_SECRET`, or clock skew over 5 minutes |
| Slack "not linked" reply | `/patchloop link <code>` with a fresh code from Integrations |
| Merge disabled, "checks are still running" | wait; in demo mode this lasts `DEMO_CHECKS_PENDING_SEC` seconds |
| Merge refused, "reconnect GitHub" | the user token expired; reconnect GitHub so a new authorization code is issued |
| "real repositories run only in an isolated Nebius Sandbox" | real repos need `PATCHLOOP_MODE=live` with Nebius credentials |
| Guest runs answer 429 | 3 per hour per IP; restart the backend to reset the in-memory limiter |
| Tokens cannot be stored | set `TOKEN_ENC_KEY` (or `DEV_MODE=true` locally) |
| Agent 401 from the backend | `AGENT_SHARED_SECRET` differs between agent and backend |
