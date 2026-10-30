# PatchLoop

Pick a bug; a team of AI agents (LangGraph: triage, parallel proposers, critic, reviewer) proposes
fixes in parallel in isolated sandboxes. **The tests decide** which fix is good, never an AI. Every
candidate goes through a deterministic policy gate and a security scan, NeMo Guardrails check the
input and the PR text, and a solved run can open a GitHub PR with the proof and alert the on-call
engineer on Slack, who reviews and merges. Agents can never merge or push to the default branch.
Also reachable from a CLI.

| Part | Path | Stack | Port |
|---|---|---|---|
| Frontend | [`frontend/`](frontend) | Next.js 16 | 3000 |
| Backend | [`backend/`](backend/README.md) | Go (Gin) + MongoDB | 8080 |
| Agent | [`agent/`](agent/README.md) | Python (FastAPI, LangGraph, NeMo Guardrails) | 8001, internal only |
| CLI | [`cli/`](cli/README.md) | Go | - |

```
browser / CLI ──> backend :8080 ──X-Agent-Secret──> agent :8001 (internal)
                     │   ^                              │
                  MongoDB └── POST /internal/runs/:id/complete
```

## Run everything

Full setup guide (GitHub App, Slack app manifest, every env var, allowed hosts, how to test each trigger,
a three-minute demo, troubleshooting): **[docs/SETUP.md](docs/SETUP.md)**.

### Local dev stack (no API keys needed)

Everything runs offline in clearly labelled fake mode: fake model, local sandbox, a Demo GitHub account with
three bundled repos (`demo/shop-api`, `demo/wordstats`, `demo/booking`), simulated pull requests and merges, and a
fake Slack API. Requirements: Go 1.27+, Node 22, Python 3.12+, and Docker or any reachable MongoDB.

```bash
scripts/dev-up.sh     # mongo (Docker, or your MONGO_URI), agent, fake Slack API, backend (DEV_MODE), frontend
scripts/e2e.sh        # signup, GitHub demo, task, SSE, PR, merge gate, follow-up, webhooks, Slack, CLI; PASS/FAIL table
node frontend/e2e/ui-real.cjs   # browser flow against the real stack (Playwright + Chromium installed separately)
scripts/dev-down.sh   # stop agent/backend/Slack/frontend (add --mongo to stop the container too)
```

- `dev-up.sh` creates a Python venv in `.logs/venv` on first run (or `AGENT_VENV=...`), generates dev-only secrets
  into `.logs/dev.env` (gitignored, mode 0600) and prints the URLs and how to sign in. Without Docker it prints
  three fixes: start Docker Desktop, set `MONGO_URI` to Atlas, or `brew install mongodb-community`.
- Options: `MONGO_URI`, `FRONTEND_MODE=prod` (production build, faster pages), `PATCHLOOP_MODE=hybrid|live`
  (needs Nebius keys in `agent/.env`), `DEMO_CHECKS_PENDING_SEC`, `SLACK_FAKE=0`, `MONGO_DB_NAME`, `FAKE_DELAY_SCALE`.
- With `DEV_MODE=true` the backend keeps OTP codes in memory and exposes `GET /internal/dev/otp?email=`
  (needs `X-Agent-Secret`), so sign-up works without email. Never set `DEV_MODE` in production.
- Guest runs (`/try`) are limited to 3 per hour per IP in memory: `e2e.sh` uses all 3, so restart the backend
  (`dev-down` + `dev-up`) between runs.
- GitHub and Slack integrations are real code paths written against the official docs and tested with mocks;
  they need a GitHub App and a Slack app (see SETUP.md) and have not been exercised against the real services here.

### Docker Compose

```bash
export AGENT_SHARED_SECRET=$(openssl rand -hex 32)        # one value for agent and backend
cp agent/.env.example agent/.env                           # fill in keys (optional: fake mode without)
cp backend/.env.example backend/.env                       # set JWT_* secrets; RESEND_API_KEY or DEV_MODE=true
docker compose up --build                                  # frontend :3000, backend :8080
AGENT_SHARED_SECRET=$AGENT_SHARED_SECRET scripts/e2e.sh   # same e2e; agent-direct checks SKIP (internal only)
docker compose down                                        # also needs AGENT_SHARED_SECRET in the env
```

The agent has no published port; only the backend reaches it on the compose network. Values in
`docker-compose.yml` `environment:` (service URLs, the shared secret) override the `.env` files.
`NEXT_PUBLIC_API_URL` (default `http://localhost:8080`) is a frontend build arg: it is inlined into
the browser bundle, so rebuild the frontend image when the public backend URL changes.

### Environment per service

| Service | Required | Optional (see each `.env.example`) |
|---|---|---|
| agent | `AGENT_SHARED_SECRET` (unset = every route but `/health` answers 401), `BACKEND_CALLBACK_URL` | `PATCHLOOP_MODE`, `PATCHLOOP_ENGINE`, `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID`, `MODEL_NANO/SUPER/ULTRA`, budgets `RUN_MAX_*`, `GUARD_*`, `NVIDIA_API_KEY`, `GITHUB_TOKEN`, `GITHUB_REPO`, `LANGSMITH_*`, `NEW_RELIC_*` |
| backend | `AGENT_SHARED_SECRET` (same value), `AGENT_URL`, `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET`, `MONGO_URI`, `CLERK_SECRET_KEY`, `RESEND_API_KEY` (unless `DEV_MODE=true`) | GitHub App: `GITHUB_APP_ID/SLUG/PRIVATE_KEY`, `GITHUB_CLIENT_ID/SECRET`, `GITHUB_WEBHOOK_SECRET`, `PUBLIC_URL`, `FRONTEND_URL`, `TOKEN_ENC_KEY`; Slack app: `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN`; `DEMO_CHECKS_PENDING_SEC`; `FRONTEND_ORIGIN` (CORS, credentials), `PUBLIC_APP_URL`, `COOKIE_SECURE`, `COOKIE_DOMAIN`, `SLACK_WEBHOOK_URL`, `NEW_RELIC_LICENSE_KEY`, `LIVE_RUNS_PER_USER_PER_DAY`, `GUEST_RUNS_PER_HOUR`, `TRUSTED_PROXIES` |
| frontend | `NEXT_PUBLIC_API_URL` (build time) | - |
| CLI | - | `PATCHLOOP_API`, `PATCHLOOP_CONFIG`, `NO_COLOR` |

### Which keys unlock which live features

Without any key everything runs: the agent uses scripted agents (`fake` mode) and a local
subprocess sandbox, guardrails use the deterministic heuristic rail, and every integration below is
a no-op.

| Feature | Key(s) | Service | Host it must reach |
|---|---|---|---|
| Real agent team (Nemotron) | `NEBIUS_API_KEY`, `MODEL_NANO`, `MODEL_SUPER` (+ `PATCHLOOP_MODE=hybrid`) | agent | `api.tokenfactory.nebius.com` |
| Nebius Sandboxes | `NEBIUS_PROJECT_ID` (+ `PATCHLOOP_MODE=live`) | agent | Nebius Sandboxes API |
| Guardrails with a safety model | `GUARD_BACKEND=auto` with Nebius, or `NVIDIA_API_KEY` | agent | `api.tokenfactory.nebius.com` / `integrate.api.nvidia.com` |
| Pull requests | `GITHUB_TOKEN`, `GITHUB_REPO` | agent | `api.github.com` |
| Agent traces | `LANGSMITH_API_KEY` | agent | `api.smith.langchain.com` |
| APM + distributed tracing | `NEW_RELIC_LICENSE_KEY` | agent, backend | `collector.newrelic.com` |
| Slack "fix ready" alert | `SLACK_WEBHOOK_URL` | backend | `hooks.slack.com` |
| OTP emails | `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | backend | `api.resend.com` |

Without `GITHUB_TOKEN`/`GITHUB_REPO`, `POST /api/runs/:id/pr` answers
`503 {"error":"pull requests are not configured: set GITHUB_TOKEN and GITHUB_REPO on the agent"}`.

### Deploy notes

Nothing here is deployed by these scripts; this is how the three services are meant to be run.

- **Agent**: `agent/Dockerfile` (python:3.12-slim, `scripts/serve.sh`, wraps New Relic only when keyed).
  Keep it on a private network: it must be reachable only by the backend. Mount a volume on
  `/srv/agent/runs` to keep saved runs (used for replays). One instance (run state is in memory).
- **Backend**: `backend/Dockerfile` (static Go binary on Alpine). Needs MongoDB (e.g. Atlas),
  `COOKIE_SECURE=true` and `COOKIE_DOMAIN` for HTTPS, `FRONTEND_ORIGIN` = the frontend's origin,
  `TRUSTED_PROXIES` = your load balancer so guest rate limits see real client IPs. SSE responses
  must not be buffered by the proxy in front of it (the backend sends `X-Accel-Buffering: no`).
  Guest rate limits are in memory: run one instance or accept per-instance limits.
- **Frontend**: `frontend/Dockerfile` (`next start`) or any Next.js host; set `NEXT_PUBLIC_API_URL`
  at build time to the public backend URL.

## Tests

```bash
(cd agent && .venv/bin/python -m pytest -q)
(cd backend && go test ./...)     # integration tests use MongoDB on localhost:27017
(cd cli && go test ./...)
(cd frontend && npm run build && npm run lint)
```
