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

### Local dev stack (no API keys needed)

Requirements: Docker (for MongoDB), Go 1.27+ (or any Go with toolchain auto-download), Node 22,
Python 3.12+ with the agent venv (`cd agent && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`),
and `npm ci` in `frontend/`. Works on Linux and macOS.

```bash
scripts/dev-up.sh     # mongo (reuses :27017 or starts container pl-mongo), agent (fake mode), backend (DEV_MODE), frontend
scripts/e2e.sh        # API + SSE + CLI end-to-end check, prints a PASS/FAIL table, exit 1 on any FAIL
node scripts/e2e/ui.cjs [screenshot-dir]   # browser check with Playwright (needs `playwright` + Chromium installed)
scripts/dev-down.sh   # stop agent/backend/frontend (add --mongo to stop the container too)
```

- `dev-up.sh` generates fresh dev-only secrets (`AGENT_SHARED_SECRET`, JWT secrets) on every start
  into `.logs/dev.env` (gitignored, mode 0600); logs go to `.logs/{agent,backend,frontend}.log`.
- Options: `PATCHLOOP_MODE=hybrid|live` (needs Nebius keys in `agent/.env`), `FRONTEND_MODE=prod`
  (`next build` + `next start` instead of `next dev`), `MONGO_DB_NAME`, `FAKE_DELAY_SCALE`.
- With `DEV_MODE=true` the backend keeps OTP codes in memory and exposes
  `GET /internal/dev/otp?email=` (needs `X-Agent-Secret`), so sign-up works without Resend.
  Never set `DEV_MODE` in production.
- Guest runs (`/try`) are limited to 3 per hour per IP in memory: `e2e.sh` uses all 3 and the
  Playwright script uses 1, so restart the backend (`dev-down` + `dev-up`) between them.

### Docker Compose

```bash
export AGENT_SHARED_SECRET=$(openssl rand -hex 32)        # one value for agent and backend
cp agent/.env.example agent/.env                           # fill in keys (optional: fake mode without)
cp backend/.env.example backend/.env                       # set JWT_* secrets; RESEND_API_KEY or DEV_MODE=true
docker compose up --build                                  # frontend :3000, backend :8080
```

The agent has no published port; only the backend reaches it on the compose network. Values in
`docker-compose.yml` `environment:` (service URLs, the shared secret) override the `.env` files.
`NEXT_PUBLIC_API_URL` (default `http://localhost:8080`) is a frontend build arg: it is inlined into
the browser bundle, so rebuild the frontend image when the public backend URL changes.

### Environment per service

| Service | Required | Optional (see each `.env.example`) |
|---|---|---|
| agent | `AGENT_SHARED_SECRET` (unset = every route but `/health` answers 401), `BACKEND_CALLBACK_URL` | `PATCHLOOP_MODE`, `PATCHLOOP_ENGINE`, `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID`, `MODEL_NANO/SUPER/ULTRA`, budgets `RUN_MAX_*`, `GUARD_*`, `NVIDIA_API_KEY`, `GITHUB_TOKEN`, `GITHUB_REPO`, `LANGSMITH_*`, `NEW_RELIC_*` |
| backend | `AGENT_SHARED_SECRET` (same value), `AGENT_URL`, `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET`, `MONGO_URI`, `RESEND_API_KEY` (unless `DEV_MODE=true`) | `FRONTEND_ORIGIN` (CORS, credentials), `PUBLIC_APP_URL`, `COOKIE_SECURE`, `COOKIE_DOMAIN`, `SLACK_WEBHOOK_URL`, `NEW_RELIC_LICENSE_KEY`, `LIVE_RUNS_PER_USER_PER_DAY`, `GUEST_RUNS_PER_HOUR`, `TRUSTED_PROXIES` |
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
