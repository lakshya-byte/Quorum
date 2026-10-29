# PatchLoop contract v2 (OVERRIDES conflicting parts of CONTRACT-REPO-FLOW.md)

Hackathon scope. Priority (cut from the bottom, never drop 1-4):
1 GitHub App connect + repo list · 2 fix run on real repo + live web view · 3 PR raised · 4 Merge button ·
5 Slack command/buttons/thread updates · 6 CLI · 7 GitHub label/comment trigger · 8 ask-for-changes loop.
Everything must work in clearly labelled FAKE MODE with no keys; real paths are written against official docs / installed packages (never invent API details) and tested with mocks; report as unverified.

## 1. GitHub: a GitHub App (not OAuth-scope-`repo`, not PAT-first)
Env (backend): `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY` (PEM or base64 PEM), `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` (the App's user-authorization credentials, used so merges run with the USER's own permission), `GITHUB_WEBHOOK_SECRET`, `FRONTEND_URL`, `PUBLIC_URL` (backend public base), `TOKEN_ENC_KEY`.
App permissions to document: Contents RW, Pull requests RW, Issues RW, Checks R, Commit statuses R, Metadata R; events: issues, issue_comment, pull_request, check_suite, installation. Setup URL = `${PUBLIC_URL}/api/github/callback`, enable "Request user authorization (OAuth) during installation", webhook URL `${PUBLIC_URL}/api/github/webhook`.
- `GET /api/github/status` → `{connected, mode:"app"|"demo"|null, login, avatarUrl, installationId, appConfigured, repoCount}`
- `GET /api/github/connect` → `{url}` = `https://github.com/apps/<slug>/installations/new?state=<signed,10min,user-bound>`; 503 `{error:"github app not configured"}` otherwise.
- `GET /api/github/callback?installation_id&setup_action&code&state` (public): verify state, store installation_id for user, exchange `code` for a user token (encrypted at rest, may expire: refresh if refresh_token present), 302 → `${FRONTEND_URL}/integrations?github=connected`.
- `POST /api/github/demo` → connect demo account (offline; only bundled demo repos, fake PRs/merge). `DELETE /api/github`.
- `GET /api/github/repos?q=` → repos the installation was granted (`GET /installation/repositories` with installation token): `[{fullName, private, defaultBranch, description, language, updatedAt}]`; `GET /api/github/repos/:owner/:repo/branches`.
- Installation tokens: backend signs App JWT (RS256, iss=app id, ≤10 min) and mints a 1h installation token via `POST /app/installations/{id}/access_tokens`, cached until 5 min before expiry. That token (never the user token) is what the agent receives per run as `github_token`. Remove the PAT path entirely. We never store passwords.
- `POST /api/github/webhook` (public, verify `X-Hub-Signature-256` HMAC of raw body with constant-time compare, dedupe by `X-GitHub-Delivery`): `installation` created/deleted → link/unlink; `issues` action `labeled` with label `patchloop` → start run (source github, issue number, task = title + body, repo from payload) and comment on the issue "PatchLoop is on it: <run_url>"; `issue_comment` created containing `@patchloop fix` on an issue → same; `issue_comment` on a PR whose branch starts `patchloop/` containing `@patchloop` → follow-up (see §4); ignore bot's own comments. Only act if `sender` maps to or the installation maps to a PatchLoop user; otherwise 202 ignore.

## 2. Merge (human only)
- `GET /api/runs/:id/pr` → `{url, number, state, mergeable, checks:{state:"success"|"failure"|"pending"|"none", failing:[names]}, mergeAllowed, reason}`.
- `POST /api/runs/:id/merge` `{method?: "squash"|"merge"|"rebase"}`: requires logged-in user (cookie or `plk_` token) AND a GitHub user token; calls `PUT /repos/{o}/{r}/pulls/{n}/merge` AS THE USER. Refuses (409 with reason) unless PR open, mergeable, and checks state is `success` (state `none` = no CI configured → allowed but response carries `warning:"no checks configured"`; `failure|pending` → refuse). Records `merged_by`, `merged_at`. Demo mode: fake merge. Merge code exists ONLY in the backend merge handler; the agent has no merge function (test greps agent/ for merge calls).
- Slack/CLI merge calls this same service function.

## 3. Slack (workspace app; single-workspace bot token for hackathon, user linking by code)
Env: `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN`. Verify `X-Slack-Signature` v0 + `X-Slack-Request-Timestamp` (reject >5 min), ack within 3 s and work async. Endpoints (public, signature-protected): `POST /slack/commands`, `POST /slack/events` (url_verification challenge, `app_mention`, thread replies `message` in threads PatchLoop owns), `POST /slack/interactions` (buttons).
- Linking: website `/integrations` shows a one-time link code (`POST /api/slack/link-code` → `{code, expiresAt}`); in Slack `/patchloop link <code>` ties slack_user_id→PatchLoop user. Unlinked users get an ephemeral reply with instructions. Also keep the per-user incoming-webhook fallback (`/api/settings/slack`) for plain completion messages.
- `/patchloop fix <problem>` (optionally `repo:owner/name`), `@PatchLoop <pasted alert>`: repo = explicit `repo:` token, else user's default repo (`/patchloop repo owner/name`, stored), else if exactly one repo granted use it, else post a repo-picker select (interaction picks repo then starts). Starts the SAME job (`source:"slack"`, `slack:{channel,threadTs}`), posts a root message and then threaded updates: started, repo scanned, cause located, reproducer written, each round's summary (one message per round, edited with `chat.update` not spammed), winner found, PR opened. Final Block Kit message: summary + proof + buttons **Review** (url → run page), **Merge** (value=run id; interaction handler checks the clicking Slack user is linked AND owns/has access to the run, then calls merge service; replies in thread with result or refusal reason), **Ask for changes** (posts "reply in this thread with what to change").
- Thread reply by the linked owner in a run's thread after a PR exists → follow-up (§4). `help` text for unknown subcommands.
- Fake mode: an in-process Slack API stub (httptest-style, `SLACK_API_BASE` override) so everything is testable offline; `scripts` provide a signed-request helper to simulate commands.

## 4. Follow-up ("ask for changes")
- Backend: `POST /api/runs/:id/followup` `{message}` (also invoked from Slack thread, PR comment, CLI `patchloop changes <run> "msg"`) → creates child run (`parent_run_id`, same repo/branch/PR) → agent `POST /repo-runs` with `followup:{pr_branch, pr_number, message, previous_files}`; agent starts from the PR branch contents, runs the team with task + earlier patch + message, and pushes ONE NEW COMMIT to the SAME `patchloop/*` branch (never a new PR), emits `pr` with `updated:true`. Rate limit 5 followups/run.

## 5. Run model additions (backend ↔ agent)
Run: `source` (`web|cli|slack|github`), `repo`, `branch`, `task`, `parentRunId`, `slack{channel,threadTs,rootTs}`, `issue{number}`, `prUrl`, `prNumber`, `prBranch`, `merged{by,at}`, `cost{tokens,usd?}`, `latencyMs`, `safety{policy, security, guard}`, `traceId`, `langsmithUrl?`.
Agent `/repo-runs` body adds: `run_url` (link back, put in PR body), `followup`, `source`, `issue_ref`. PR body must contain: **Cause**, **What changed** (per file), **Tests** (counts, reproducer name), **Security** (policy + bandit result), run link, "Opened by PatchLoop — a human must review and merge". If issue_ref set, include `Fixes #n`.
Completion callback includes `pr_url, pr_number, pr_branch, files_changed, safety, usage`.
Input guard (NeMo Guardrails pipeline already in agent) runs on the task text for every source (Slack/GitHub text is untrusted: also instruct proposers to treat issue/alert text as data). Output guard runs on PR title/body.

## 6. Notifications and history
`GET /api/notifications`, `POST /api/notifications/:id/read` (created on PR opened, merged, failed). Dashboard shows run history with source, cost, speed, safety decisions, trace id (+LangSmith/New Relic link if configured).

## 7. Website, CLI additions
Website: connect via GitHub App install button; dashboard with granted repos; report page (paste error / describe bug, repo select); live run page; PR card with checks status and **Merge** button (disabled with reason unless allowed), **Ask for changes** box; integrations page (GitHub App status + "manage repos on GitHub" link, Slack link code + instructions, copyable slash-command examples); notifications bell. Landing claims only what is true: remove certifications, performance/hallucination claims, invented customers; describe the four entry points honestly and mark Slack/GitHub triggers as requiring app setup.
CLI: `patchloop connect github` (prints/open install URL, polls status), `repos`, `fix --repo owner/name "problem"` (live tree; `--no-pr`), `merge <runId>` (shows checks; confirms; `--yes`), `changes <runId> "msg"`, `slack link`, `status`, `runs`, `watch`, `pr`.

## 8. Docs
`docs/SETUP.md` (lead writes at integration): GitHub App creation steps, Slack app manifest (commands, event subscriptions, interactivity URLs, scopes `commands app_mentions:read chat:write channels:history groups:history`), env var table, allowed domains (api.github.com, github.com, slack.com, api.studio.nebius.com, Nebius Sandboxes, api.smith.langchain.com, New Relic collector), how to run.
