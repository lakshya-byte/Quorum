# PatchLoop agent

Python service that does the debugging for PatchLoop. Given a bug (report + buggy file + tests), a
**team of AI agents** proposes fixes in parallel, every candidate is gated by a deterministic policy,
tested in an isolated sandbox and scanned with bandit, and the **tests decide** which fix wins, never
an LLM. Agents never merge and never push to the default branch: the winner becomes a PR for a human.

Internal service: the Go backend (`../backend`) is its only caller.

## Setup

```bash
cd agent
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt        # pinned; verified on Python 3.13 (Docker image uses 3.12)
cp .env.example .env                    # fill in what you need; empty values fall back to defaults
scripts/serve.sh                        # uvicorn on $PORT (8001); wraps newrelic-admin if NEW_RELIC_LICENSE_KEY is set
```

Docker: `docker build -t patchloop-agent . && docker run --env-file .env -p 8001:8001 patchloop-agent`.

## Modes and engines

| Mode | Agents | Sandbox | Cost |
|---|---|---|---|
| `fake` (default) | scripted team (`FakeTeam`) | local subprocess | free, offline |
| `hybrid` | Nemotron on Nebius Token Factory | local subprocess | LLM tokens |
| `live` | Nemotron on Nebius Token Factory | Nebius Sandboxes (Contree) | LLM tokens + sandboxes |

Without `NEBIUS_API_KEY` + `MODEL_NANO` runs use `fake`; `live` without `NEBIUS_PROJECT_ID` runs as
`hybrid`; after `MAX_LIVE_RUNS` non-fake runs since boot, new runs use `fake`. `POST /runs` always
returns the mode actually used.

`engine` (per run, default `PATCHLOOP_ENGINE=graph`):

- **graph**: the LangGraph agent team below.
- **loop**: the original beam search (`app/search.py`), kept as a fallback. Same events and node fields
  (it has no triage/critic events).

## The team (engine=graph, `app/graph_engine.py`)

```
START ─┬─ input_guard ─┐
       ├─ triage ──────┼─> plan_round ──Send×3──> propose ──> select ─┬─ solved ──────> finish ─> reviewer ─> output_guard
       └─ baseline ────┘       ^                                       ├─ rounds left ─> critic (Send per survivor)
                               └───────────────────────────────────────┴───────────────┘
```

1. `input_guard`, `triage` and `baseline` (testing the original code = node 0) run concurrently.
2. **Triage** (Nano) returns `{cause, 3 distinct strategies}`.
3. One **proposer** per strategy via LangGraph `Send` (verified in `langgraph/types.py`, v1.2.18);
   round 1 uses `MODEL_NANO`, later rounds `MODEL_SUPER`. Each returns a COMPLETE file + one-line idea.
4. Each candidate, the moment it arrives: policy gate → sandbox tests → bandit → score → `node` event
   (`app/candidate.py`, shared with the loop engine). Results are cached by sha256(code + tests).
5. **Early exit**: the first candidate that passes every test and the gate sets the round's event;
   in-flight sibling LLM calls and sandbox runs are cancelled (asyncio cancellation; local test
   subprocesses are killed; for Nebius the client stops waiting, the remote instance ends at its timeout).
6. `select` keeps the top 2 (tests decide; ties → smaller diff via the score's diff penalty).
7. **Critic** (Super) runs only for survivors, in parallel; input = failing test output; output = one
   short lesson fed to the next round's proposer for that parent. Skipped if a single survivor already scores 1.0.
8. `finish` emits `done` first. The **reviewer** (Super) then writes PR title/body/risk off the critical
   path, and the **output guard** checks that text. `POST /runs/{id}/pr` uses the draft only if it passed.

Structured output: Nemotron's JSON-schema/tool support on Nebius could not be checked here (Nebius is
blocked in this environment), so triage/critic/reviewer use JSON-in-a-fence + pydantic + one corrective
retry. One pooled `httpx.AsyncClient` per process is shared by all `ChatOpenAI` instances.
Note: `langchain-openai` 1.7 sends `max_completion_tokens` (vLLM-style servers accept it; unverified against Nebius).

**Fake mode** exercises the whole graph with scripted agents. For every bug: round 1 = a partial fix,
a wrong fix and a test-tampering attempt the policy gate blocks; critics write lessons from the failing
test names; round 2 = the fix built on the partial survivor solves it, and a slow sibling is cancelled
by early exit. So the demo shows every event type.

## Safety

**Policy gate** (`app/policy.py`, no LLM, fail-closed, every candidate): only the target file may change;
test files must be byte-identical (the harness always writes the original tests anyway); diff ≤
`POLICY_MAX_DIFF_LINES` (60); the code must parse; AST denylist: `os.system`/`popen`/`exec*`/`spawn*`,
`subprocess`, `socket`, `requests`/`httpx`/`urllib`, `eval`, `exec`, `__import__`, `compile`, `ctypes`,
dunder escapes, `open()` unless a relative literal path inside the working dir. Violations score 0, are
never run, and emit `node.policy = {ok: false, reasons}`.

**Security stage** (`app/security.py`): bandit `-f json` on the original file (baseline, from node 0)
and on each candidate; any NEW medium/high finding blocks the candidate (`node.security.ok=false`,
score 0). Local runs use the installed bandit; Nebius runs use a tool image (python:3.12-slim + bandit
1.9.4) built once at startup and cached by UUID in `agent/.cache/tool_image.json` (gitignored), with
tests + scan in one disposable instance.

**Network isolation**: contree-sdk 0.3.6 exposes no networking option (`InstanceSpawnRequest` has
command/image/env/files/timeout/... and nothing network related), so AI-written code in Nebius
Sandboxes runs with the platform's default network policy. The policy gate's denylist (no sockets,
HTTP clients, subprocess) is the mitigation. The local sandbox runs with a minimal env (no secrets).

**Budgets per run**: `RUN_MAX_TOKENS`, `RUN_MAX_SECONDS`, `RUN_MAX_CANDIDATES`. Exceeding stops the run
with `error {stage:"budget"}` followed by `done` with the best node so far.

**Guardrails** (`app/guard.py`, `guardrails/`): NVIDIA NeMo Guardrails 0.24.1, rails-only via
`LLMRails.check_async(messages, rail_types=[INPUT|OUTPUT])`, never used to generate. Built once at
startup and warmed up. Backend probe (`GUARD_BACKEND=auto`), logged at startup:

1. `nebius`: `GET {nebius}/models` lists a model whose id contains safety/guard/nemoguard → NeMo
   `content safety check input/output $model=content_safety` (engine openai at the Nebius base URL).
2. `nvidia`: `NVIDIA_API_KEY` set and NVIDIA's model list has one → same rail, engine `nim`.
3. `self`: NeMo `self check input/output` with `MODEL_NANO`.
4. `heuristic`: fake mode or no LLM credentials → deterministic regex rail (prompt injection, role hijack,
   push/merge to main, test tampering, secret exfiltration, remote code, chat-template injection),
   implemented as a NeMo custom action so it still goes through NeMo. Labelled `backend:"heuristic"`.

The heuristic rail runs first in every backend. Input rail: bug report + source (UNTRUSTED; prompts also
wrap them in `<untrusted>` tags). Output rail: PR text only. Timeout `GUARD_TIMEOUT` (2.5s);
`GUARD_FAIL_MODE=closed|open` (default closed for live/hybrid, open for fake/replay). Every check emits
a `guard` event. An input block stops the run before any proposal (`error {stage:"input_guard"}`).

## HTTP API

All routes except `/health` require `X-Agent-Secret: <AGENT_SHARED_SECRET>` (401 otherwise).

| Method | Path | Result |
|---|---|---|
| GET | `/health` | `{status, mode, engine, guard_backend, langsmith, newrelic}` |
| GET | `/bugs` | `[{id, title, issue, tier}]`, tier `easy` or `hard` |
| POST | `/runs` | `{bug_id, user_id?, engine?: "graph"\|"loop", model_override?, replay?}` → `{run_id, mode, engine, trace_id}` |
| GET | `/runs/{id}/events` | Server-Sent Events (below) |
| GET | `/runs/{id}` | `{run_id, bug_id, mode, engine, status, events, pr_draft, pr_url}` |
| POST | `/runs/{id}/pr` | opens a PR from a `patchloop/*` branch → `{url}`; 400 if unsolved |
| GET | `/replays`, POST `/replays/{run_id}` | saved solved hybrid/live runs; re-stream one |

`replay: true` re-streams the best saved real run for that bug (~0.3s per event, no LLM/sandbox);
with nothing saved it falls back to a `fake` run.

### Event stream

Each message is `data: {"type": T, "data": {...}}\n\n`, pushed the moment it is emitted (no polling):

- `run_started` `{run_id, bug_id, mode, engine}`
- `guard` `{stage: input|output, verdict: pass|block, reasons, latency_ms, backend}`
- `triage` `{cause, strategies}`
- `round` `{depth}`
- `node` `{id, parent, depth, idea, strategy, code, output, passed, total, score, model, latency_ms, tokens, policy:{ok,reasons}, security:{ok,new_findings}}`
- `critic` `{node_id, lesson, model}`
- `done` `{solved, best, usage:{calls,prompt_tokens,completion_tokens}, latency_ms, time_to_first_node_ms, engine, rounds?, candidates?, cancelled?}`
- `pr` `{url}` (appended when a PR is opened)
- `error` `{stage, message}`
- `end` always last

### Completion callback

On finish the run is saved to `runs/<id>.json` and POSTed to
`{BACKEND_CALLBACK_URL}/internal/runs/{run_id}/complete` (header `X-Agent-Secret`, plus `traceparent`):
`{run_id, user_id, bug_id, mode, engine, solved, best_node_id, nodes, usage, latency_ms}`. Failures are logged and ignored.

## Observability

- **LangSmith**: on only if `LANGSMITH_API_KEY` is set (`LANGSMITH_TRACING=true`, project `LANGSMITH_PROJECT`).
  Every agent call is a LangChain runnable (`ChatOpenAI` live, `RunnableLambda` fake), tagged
  `run_id:…, bug_id:…, engine:…, mode:…` with the same metadata.
- **New Relic**: `scripts/serve.sh` runs `newrelic-admin run-program uvicorn …` only when
  `NEW_RELIC_LICENSE_KEY` is set (`NEW_RELIC_APP_NAME=patchloop-agent`); otherwise nothing NR is loaded
  and every helper is a no-op. The installed agent (14.1.0) has `mlmodel_openai` and `mlmodel_langchain`
  hooks, so `NEW_RELIC_AI_MONITORING_ENABLED=true` is set to auto-capture LLM calls. Its LangGraph hooks
  only cover `create_agent()` agents, so graph nodes, guard checks and sandbox calls get manual
  `FunctionTrace` spans and each run is a `BackgroundTask` joined to the caller's W3C trace. Custom events:
  `PatchLoopRun {run_id,bug_id,engine,mode,solved,rounds,candidates,tokens,latency_ms,ttfn_ms}`,
  `PatchLoopAgentStep {run_id,agent,model,latency_ms,tokens,ok}`, `PatchLoopGuard {stage,verdict,latency_ms,backend}`.
- **Logs**: JSON lines with `run_id` and `trace_id` (from the incoming `traceparent`, or a new one). Secrets are masked.

## Bugs and evals

4 `easy` bugs (paginate, slugify, cart, average: single-shot Nano solved all of them) and 5 `hard` ones
(`app/bugs_hard.py`): vague user-style reports, 2-3 layered defects, exact rules only in the tests:
`money_total` (Decimal, half-up, coupon before tax, floor at 0), `version_sort` (1.10 > 1.9, pre-release
< release, leading v), `merge_intervals` (adjacent merge, unsorted, no mutation), `lru_cache` (get
refreshes recency, update without eviction, capacity 0), `slugify_unicode` (accents, collapse, ≤40
chars with no trailing dash). Each has wrong/partial/correct versions; `scripts/04_check_bugs.py`
checks buggy < partial < correct for all 9.

```bash
python scripts/eval.py --engine single|loop|graph --n 5 --tier hard [--live] [--nebius-sandbox]
```

Prints a markdown table (solve rate, tokens per solve, p50/p95 latency, guard-block rate), writes
`evals/results/*.json`, and with `LANGSMITH_API_KEY` runs the attempts as a LangSmith experiment on
dataset `patchloop-<tier>`. `--live` checks credentials and reachability first and exits rather than
reporting fake numbers. **Hard-tier calibration is pending**: target is 20-70% single-shot Nano solve
rate; run `python scripts/eval.py --engine single --n 5 --tier hard --live` and adjust the bugs if outside.

## Scripts

| Script | What it does |
|---|---|
| `scripts/serve.sh` | start the service (with New Relic when keyed) |
| `scripts/01_hello_llm.py` | lists Nemotron models and asks one to say hello |
| `scripts/02_hello_sandbox.py` | runs `python --version` in a Nebius Sandbox |
| `scripts/03_fork_spike.py` | proves checkpoint forks are isolated |
| `scripts/04_check_bugs.py [--tier]` | buggy < partial < correct for every bug |
| `scripts/05_run_fake.py [bug] [--engine graph\|loop]` | full fake run, prints events and the tree |
| `scripts/06_benchmark.py [N] [--live]` | legacy single-shot vs loop benchmark (easy bugs) |
| `scripts/eval.py` | evals (above) |

## Repo tasks (`POST /repo-runs`)

Point the team at a whole repository and a plain-English task; it opens a PR from a `patchloop/*` branch.

```bash
curl -X POST localhost:8001/repo-runs -H "X-Agent-Secret: $AGENT_SHARED_SECRET" -H 'content-type: application/json' \
  -d '{"task":"Checkout totals are wrong with coupons","repo":{"full_name":"demo/shop-api","branch":"main"},
       "github_token":null,"auto_pr":true,"source":"web","run_url":"https://app.example/runs/1"}'
curl -N localhost:8001/runs/<run_id>/events -H "X-Agent-Secret: ..."     # SSE
```

Body: `task` (<=4000), `repo{full_name,branch}`, `github_token` (per run, the short-lived GitHub App installation
token), `user_id`, `engine` (repo runs always use the graph engine), `auto_pr`, `run_url` (linked in the PR body),
`source` (`web|cli|slack|github`), `issue_ref` (adds `Fixes #n`), and `followup{pr_branch,pr_number,message,previous_files}`.
`POST /runs/{id}/pr {github_token}` opens the PR later (idempotent). `GET /demo-repos` lists the bundled repos.

Event order: `run_started`, `repo`, `guard`, `locate`, `repro`, `triage`, `node`(baseline), `round`, `node`..., `critic`,
`done`, `guard`(output), `pr`, `end`. The input guard runs right after `repo` (before any agent reads the
task) instead of after `repro`: issue/alert text is untrusted, so it is checked first and wrapped in `<untrusted>` tags in every prompt.

- **Repo loading** (`repo_loader.py`): GitHub tarball with the token (25 MB / 3000 files / 200 KB per file; skips vendor
  and binary files; symlinks, hardlinks, traversal and absolute paths are dropped). `demo/<name>` (or any name in fake mode)
  loads a bundled offline repo from `app/demo_repos/` (`shop-api` needs a 2-file fix, `wordstats`, `booking`).
- **Detection** (`repo_detect.py`): Python unittest/pytest (solid), `npm test` and `go test ./...` (best-effort, marked
  `support: best-effort`; reproducer writing is Python only).
- **Agents**: locator (live LLM, deterministic keyword/scripted in fake), test-writer (reproducer accepted only if it
  FAILS on the original and is not a broken test), multi-file proposers, critic, reviewer. All run through the existing LangGraph engine
  via an adapter (`repo_eval.py`); success = reproducer and existing suite pass. The first passing candidate cancels the siblings.
- **Gate**: every path is validated (no traversal, `.git`/`.github`, existing tests are immutable, only the byte-identical
  reproducer may be a new test, <=10 files, AST rules on Python), bandit runs on every changed file against its original.
- **PR** (`repo_pr.py`): blobs -> tree -> one commit -> ref -> pull request through the GitHub git-data API, on `patchloop/<slug>-<unix>`
  only (enforced in code). Follow-ups push ONE new commit to the same branch and emit `pr` with `updated:true`. Demo repos get a fake PR
  (`fake:true`, `https://github.com/demo/<repo>/pull/<n>`). The service has no call that completes a PR; a test greps for it.
- **Token hygiene**: held in memory on the run object only, `SecretStr` in the request, redacted from errors, cleared after the PR
  attempt; tests scan events, the saved record, API output and logs for it.
- **Real repos run their tests only in a Nebius Sandbox** (live mode); on the agent host only with `ALLOW_LOCAL_REPO_EXEC=1`.
- `done` carries `usage` (tokens, `cost_usd` when `PRICE_IN_PER_MTOK`/`PRICE_OUT_PER_MTOK` are set, `latency_ms`,
  `time_to_first_event_ms`) and `safety{guard, policy, security}`. LangSmith metadata and the `PatchLoopRun` New Relic event carry
  run_id, repo, source, kind, cost.
- Completion callback adds `kind:"repo"`, `repo`, `branch`, `task`, `pr_url`, `pr_number`, `pr_branch`, `files_changed`,
  `safety`, `usage`, and is sent after the PR attempt.

## Tests

```bash
pytest -q      # fake mode, no network (2 guard tests need nemoguardrails installed)
```

## Not verifiable in the build environment

These hosts are blocked there, so all of these ran only in fake mode: Nebius LLM + Sandboxes
(`api.tokenfactory.nebius.com`, `NEBIUS_API_KEY`), LangSmith (`api.smith.langchain.com`,
`LANGSMITH_API_KEY`), New Relic (`collector.newrelic.com`, `NEW_RELIC_LICENSE_KEY`), the NVIDIA guard
backend (`integrate.api.nvidia.com`, `NVIDIA_API_KEY`), live latency budgets, and the hard-tier calibration.
