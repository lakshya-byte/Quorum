# PatchLoop: repo flow contract (v1)

Product flow (the single thing this build delivers):

1. User signs in, **connects GitHub** (OAuth, or personal-access-token fallback, or Demo account offline).
2. Picks a **repo + branch** (the product reads the whole repo).
3. Writes a **task** in plain English ("pagination returns the wrong last page").
4. A team of **agents** works it (diagram 2: guard/triage → locator → test-writer → 3 parallel proposers → policy gate → sandbox tests → security scan → score → critic → next round; first passing candidate cancels the rest → reviewer → output guard).
5. **Slack** message when done (per-user webhook, falls back to global `SLACK_WEBHOOK_URL`), with a PR link.
6. A **PR is open on GitHub**, branch `patchloop/*`, ready to merge. **No code anywhere merges or pushes to the default branch.**
7. **CLI** does all of it: `patchloop connect github | repos | fix | slack | runs | watch | pr`.

Everything must work **offline in fake mode** (no keys): a Demo GitHub account with bundled demo repos, fake model, local sandbox, fake PR URL (`https://github.com/demo/<repo>/pull/<n>`, event flag `fake: true`). Real paths are written to the same interfaces and unit-tested with mocks; report them honestly as unverified.

## Agent service (Python, `agent/`), header `X-Agent-Secret` as today

`POST /repo-runs`
```json
{ "task": "string (<=4000)", "repo": {"full_name": "owner/name", "branch": "main"},
  "github_token": "string|null  (per-run, never logged, never persisted, never in events/records)",
  "user_id": "string|null", "engine": "graph|loop|null", "auto_pr": true }
```
→ `{ "run_id", "mode", "engine", "trace_id" }`. `repo.full_name` starting with `demo/` or fake mode ⇒ bundled demo repos in `agent/app/demo_repos/` (3 small Python repos, multi-file, with unittest suites and one real bug each; at least one needs a 2-file fix).
`GET /runs/{id}/events` SSE (same as today). `GET /runs/{id}`. `POST /runs/{id}/pr` (idempotent, opens PR for a solved repo run if `auto_pr` was false; needs token again in body `{ "github_token" }`).

New SSE event types (all `{type, data}`), emitted in this order, then existing `guard`, `triage`, `round`, `node`, `critic`, `done`, `error`:
- `repo` `{full_name, branch, files, language, test_command, truncated}`
- `locate` `{files: [{path, reason}]}`
- `repro` `{path, test_name, failed_on_original: true, output_tail}` (accepted only if it FAILS on the original code; otherwise emit `repro` with `failed_on_original:false` and continue with existing tests only)
- `node` data gains `files: {path: content}` (multi-file candidate; `code` kept = primary file for old UI) and `diff` (unified diff text, capped 20k chars)
- `done.best` is the node object (unchanged). Success = reproducer AND existing suite pass.
- `pr` `{url, branch, number, fake}` emitted after done if solved and auto_pr. PR body: issue/task, winning idea, proof counts, test tail, risk (reviewer draft). Branch `patchloop/<slug>-<unix>`; code must refuse any branch not starting with `patchloop/`; there must be no merge call anywhere (a test greps for `merge`).

Completion callback to backend `/internal/runs/{id}/complete` gains: `kind:"repo"`, `repo`, `branch`, `task`, `pr_url`, `pr_number`, `files_changed`. Callback is sent AFTER the PR attempt so it carries `pr_url`.

Repo handling: real GitHub = tarball download via API with the token, size cap 25 MB / 3000 files, skip binary/vendor dirs; language detect: Python (unittest/pytest), then Node (`npm test`), Go (`go test ./...`) — Python must be solid, others best-effort and clearly marked. Sandbox: live mode uploads the repo once as a checkpoint and forks per candidate; local mode uses temp dirs. Security: path traversal checks on every candidate file path, patches may only touch existing or new files inside the repo, never `.github/`, never test files except the new reproducer.

## Backend (Go, `backend/`), all under `/api`, cookie or Bearer (`plk_`) auth

GitHub:
- `GET  /github/status` → `{connected, login, avatarUrl, mode: "oauth"|"pat"|"demo"|null, oauthAvailable}`
- `GET  /github/connect` → `{url}` (GitHub authorize URL, `state` = signed, 10 min, bound to user; scope `repo`; 503 `{error:"github oauth not configured"}` if `GITHUB_CLIENT_ID/SECRET` unset)
- `GET  /github/callback?code&state` (public) → exchanges code, stores token, 302 to `${FRONTEND_URL}/integrations?github=connected` (or `?github=error&reason=`)
- `POST /github/token` `{token}` → validates via GitHub `GET /user`, stores (mode pat)
- `POST /github/demo` → connects fake account `demo-user` (mode demo; allowed always, it only exposes bundled demo repos)
- `DELETE /github` → disconnect
- `GET  /github/repos?q=&page=` → `[{fullName, private, defaultBranch, description, language, updatedAt}]` (demo mode: 3 demo repos)
- `GET  /github/repos/:owner/:repo/branches` → `[{name, default}]`
Tokens are AES-256-GCM encrypted at rest (`TOKEN_ENC_KEY` base64 32B; if unset in DEV_MODE derive from JWT secret, otherwise refuse to start storing). Never logged, never returned.

Slack: `GET/PUT/DELETE /settings/slack` (`{configured, webhookUrlMasked}` / `{webhookUrl}` must match `^https://hooks\.slack\.com/`), `POST /settings/slack/test` sends a test card. Completion posts Block Kit with repo, task, result, attempts, PR button; uses the user's webhook else global; a failed Slack post never fails the run.

Tasks: `POST /tasks` `{repo:"owner/name", branch, task, autoPr?:true}` → `{runId}`; decrypts the user's token and calls agent `/repo-runs`; 409 `{error:"connect github first"}` if not connected; Run model gains `kind` (`bug`|`repo`), `repo`, `branch`, `task`, `prNumber`, `filesChanged`. `GET /runs` and `/runs/:id` include them; SSE relay unchanged and covers repo runs. `POST /runs/:id/pr` works for repo runs (re-sends token). Guests cannot create repo tasks. Rate limit: 10 tasks/hour/user.
Env additions: `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_REDIRECT_URL`, `FRONTEND_URL`, `TOKEN_ENC_KEY`.

## CLI (`cli/`), same config file as today
`patchloop connect github` (prints URL and tries to open it; `--token <pat>` posts a PAT; `--demo`), `patchloop repos [--q]`, `patchloop fix --repo owner/name [--branch main] "task"` (creates the task, streams a readable live view with each stage and candidate, prints the PR URL, exit code 0 solved / 1 unsolved / 2 error; `--no-pr`, `--json`), `patchloop slack set <url> | test | clear`, `patchloop status` (github, slack, api). Existing commands keep working.

## Frontend (`frontend/`, Next.js)
Design bar: a professional, finished product, not a template. One consistent design system (tokens, type scale, spacing, dark theme, focus states, empty/loading/error states, responsive down to 375px, accessible, no layout shift). Honest copy only (no invented customers, certifications or metrics).
- **Landing `/`**: hero with a one-line promise and a looping product demo (the real attempt-tree component fed by scripted events), a "how it works" section that draws diagram 2 (agent team) and diagram 1 (system map: you → PatchLoop → GitHub/Nebius/Slack, "agents never merge") as clean SVG, the 7-step flow, a trust section (tests are the judge, sandboxed, PR only, never merges), CTA to `/signup` and `/try`, polished footer.
- **App shell** (sidebar + topbar, mobile drawer) for: `/dashboard` (runs table, status chips, stats), `/new` (stepper: 1 repo+branch picker with search, 2 task box with examples, 3 review & start), `/runs/[id]` (live pipeline: stages repo→locate→repro→propose→test→critic→review→PR, attempt tree, diff viewer, PR card with button, Slack-sent indicator), `/integrations` (GitHub card: connect OAuth / paste token / use demo, repo count, disconnect; Slack card: webhook + test), `/settings/tokens`, `/try` (guest demo stays).
- Onboarding checklist on dashboard when GitHub or Slack not set up.
- Update `frontend/mocks/server.mjs` to implement every endpoint above (demo GitHub, demo repos, a repo run stream with all new event types) so the UI runs with no backend. Docs pages updated.

## Integration
`scripts/dev-up.sh` detects missing Docker and prints three fixes (start Docker Desktop, set `MONGO_URI` to Atlas, `brew install mongodb-community`), and if `MONGO_URI` is set skips Docker. `scripts/e2e.sh` gains the full flow: signup → demo-connect GitHub → list repos → set Slack webhook (local capture server) → create task → stream to done → PR event → Slack capture received → run listed. Playwright test walks the UI flow. READMEs and `.env.example` files updated.

## Definition of done
All suites green (`agent` pytest, backend + cli `go test`, frontend `npm run build` + lint 0 errors), e2e green against the real stack in fake mode, screenshots of landing/new/run/integrations reviewed at desktop and 375px. Final report separates **verified here** from **unverified (needs keys)**.
