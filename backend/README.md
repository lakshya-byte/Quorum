# PatchLoop backend

Go (Gin) + MongoDB API in front of the internal Python agent. It owns users, auth, run records,
API tokens and notifications, and relays each run's live event stream from the agent to the
browser or CLI without buffering. Agents never merge: the backend only stores results, opens a PR
on request, and alerts a human on Slack.

```
browser / CLI ──HTTPS──> backend :8080 ──X-Agent-Secret──> agent :8001 (internal)
                              ^                                 │
                              └──── POST /internal/runs/:id/complete (callback)
```

## Run

```bash
cd backend
cp .env.example .env    # fill in secrets
go run ./cmd/api
```

Local demo without the real agent (contract-compatible fake that streams every event type):

```bash
AGENT_SHARED_SECRET=dev BACKEND_CALLBACK_URL=http://localhost:18080 go run ./cmd/fakeagent -addr :18001
PORT=18080 AGENT_URL=http://localhost:18001 AGENT_SHARED_SECRET=dev DEV_MODE=true \
  JWT_ACCESS_SECRET=a JWT_REFRESH_SECRET=b MONGO_DB_NAME=patchloop_backend_dev go run ./cmd/api
```

The fake agent's bug `crash` drops its connection mid-stream; `unsolved` ends unsolved.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | listen port |
| `MONGO_URI` / `MONGO_DB_NAME` | `mongodb://localhost:27017` / `patchloop` | database |
| `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET` | required | cookie session signing |
| `JWT_ACCESS_TTL_MIN` / `JWT_REFRESH_TTL_DAYS` | `15` / `30` | session lifetimes |
| `RESEND_API_KEY` | required unless `DEV_MODE=true` | OTP email delivery |
| `RESEND_FROM_EMAIL` | `noreply@patchloop.dev` | sender |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | CORS origin (credentials allowed) |
| `PUBLIC_APP_URL` | `FRONTEND_ORIGIN` | base for links, e.g. `{PUBLIC_APP_URL}/runs/{id}` |
| `OTP_TTL_MIN` | `10` | OTP lifetime |
| `COOKIE_SECURE`, `COOKIE_DOMAIN` | `false`, `localhost` | cookie attributes |
| `AGENT_URL` | `http://localhost:8001` | internal agent base URL |
| `AGENT_SHARED_SECRET` | required | `X-Agent-Secret` both ways |
| `LIVE_RUNS_PER_USER_PER_DAY` | `10` | over the cap, runs fall back to replay (response `notice`) |
| `GUEST_RUNS_PER_HOUR` | `3` | guest demo runs per IP (token bucket, in memory) |
| `TRUSTED_PROXIES` | empty | proxies allowed to set `X-Forwarded-For` |
| `SLACK_WEBHOOK_URL` | empty (off) | Block Kit alert when a run is solved / a PR opens |
| `NEW_RELIC_LICENSE_KEY` | empty (off) | APM, distributed tracing, custom events |
| `NEW_RELIC_APP_NAME` | `patchloop-backend` | APM app name |
| `DEV_MODE` | `false` | test only: OTPs readable at `/internal/dev/otp` |

## API

Errors are always `{"error": "message"}`. Auth is the access cookie **or**
`Authorization: Bearer plk_...` (API token).

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/api/auth/{signup,verify-otp,resend-otp,login,refresh,logout}` | - | cookie session |
| GET | `/api/auth/me` | user | |
| GET | `/api/bugs` | user | from the agent |
| POST | `/api/runs` | user | `{bugId, engine?: "loop"\|"graph", replay?}` → `{runId, mode, engine, notice?}` |
| GET | `/api/runs` | user | my runs, newest first (without nodes) |
| GET | `/api/runs/:id` | owner | `{id,userId,bugId,agentRunId,mode,engine,status,solved,bestNodeId,nodes,usage,latencyMs,prUrl,createdAt,completedAt}` |
| GET | `/api/runs/:id/events` | owner | SSE passthrough |
| POST | `/api/runs/:id/pr` | owner | → `{url}`, stored as `prUrl` |
| POST | `/api/tokens` | user | `{name}` → `{token}` (plaintext shown once, `plk_` prefix) |
| GET | `/api/tokens` | user | list (no secrets) |
| DELETE | `/api/tokens/:id` | user | revoke |
| GET | `/api/demo/bugs` | - | public bug list |
| POST | `/api/demo/runs` | - | `{bugId}`; always replay/fake; `GUEST_RUNS_PER_HOUR` per IP, then 429 + `Retry-After` |
| GET | `/api/demo/runs/:id/events` | - | SSE, guest runs only |
| POST | `/internal/runs/:agentRunId/complete` | `X-Agent-Secret` | agent completion callback |
| GET | `/internal/dev/otp?email=` | `X-Agent-Secret` | only registered when `DEV_MODE=true` |

### Event stream

`/events` proxies `{AGENT_URL}/runs/{agentRunId}/events` through `httputil.ReverseProxy` with
`FlushInterval: -1` and `Cache-Control: no-cache`, `X-Accel-Buffering: no`. Events pass through
byte-for-byte (`data: {"type":T,"data":{...}}`). The upstream request carries the client's context,
so closing the client cancels the agent stream. If the agent dies mid-stream or is unreachable,
the client gets

```
data: {"type":"error","data":{"stage":"relay","message":"..."}}
data: {"type":"end"}
```

instead of a hang. Measured relay overhead in tests: < 1 ms per event.

## Observability

- JSON logs (`log/slog`) with `trace_id` and `run_id`; emails and secrets are never logged.
- W3C `traceparent` is continued from the caller (or started) and sent on every agent call,
  including the SSE request. With New Relic enabled the agent's DT headers are used.
- New Relic (`nrgin`): one transaction per route, distributed tracing, custom events
  `RunRequested`, `RunCompleted`, `SlackNotified`. Without a license key all of it is a no-op;
  custom events are still written to the JSON log.

## Tests

```bash
go test ./...
```

Integration tests use MongoDB on `localhost:27017`, database `patchloop_backend_test` (reset at
start; skipped if Mongo is down), a fake agent and a fake Slack webhook (`httptest`).
