# PatchLoop agent

Python service that does the debugging for PatchLoop. Given a broken function and its tests it
runs a **beam search**: ask an LLM for several different fixes, test every candidate in its own
isolated sandbox at the same time, keep the best few, feed their failing test output back to the
LLM, and repeat. It stops when a candidate passes every test or the depth limit is reached.
**The tests are the judge, never the LLM.**

It is an internal service: the Go backend (`../backend`) is its only caller.

## Setup

```bash
cd agent
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in what you need
uvicorn app.main:app --port 8001
```

Python 3.11+ is required. Docker: `docker build -t patchloop-agent . && docker run --env-file .env -p 8001:8001 patchloop-agent`.

## Modes

| Mode | Proposer | Sandbox | Cost |
|---|---|---|---|
| `fake` (default) | scripted fixes from `app/bugs.py` | local subprocess | free, offline |
| `hybrid` | Nemotron on Nebius Token Factory | local subprocess | LLM tokens |
| `live` | Nemotron on Nebius Token Factory | Nebius Sandboxes (Contree) | LLM tokens + sandboxes |

Safety valves:
- Every non-fake run increments a counter. Once it exceeds `MAX_LIVE_RUNS` (since boot), new runs
  silently use `fake`. The `mode` returned by `POST /runs` is always the mode actually used.
- Without `NEBIUS_API_KEY` and `MODEL_NANO`, runs use `fake`. `live` without `NEBIUS_PROJECT_ID` runs as `hybrid`.

## Environment

| Variable | Meaning |
|---|---|
| `PORT` | HTTP port (default `8001`) |
| `AGENT_SHARED_SECRET` | Value the caller must send in `X-Agent-Secret` |
| `BACKEND_CALLBACK_URL` | Go backend base URL for completion callbacks (empty disables them) |
| `NEBIUS_API_KEY` | Nebius key, used for Token Factory and Sandboxes |
| `NEBIUS_PROJECT_ID` | Nebius project for Sandboxes |
| `MODEL_NANO` | Model for the first round of fixes |
| `MODEL_SUPER` | Model for deeper rounds (falls back to `MODEL_NANO`) |
| `MODEL_ULTRA` | Not used by default; pass it as `model_override` for benchmarks |
| `PATCHLOOP_MODE` | `fake` \| `hybrid` \| `live` |
| `MAX_LIVE_RUNS` | Max non-fake runs since boot (default 15) |
| `GITHUB_TOKEN`, `GITHUB_REPO` | Token and `owner/repo` for opening fix PRs |

Search constants live in `app/config.py`: `BRANCH=3` fixes per frontier node, `BEAM=2` kept per
round, `MAX_DEPTH=3` rounds, test timeouts 20s local / 60s sandbox.

## How the search works

1. Node 0 is the original buggy code; it is tested first.
2. Each round, every frontier node gets `BRANCH` children. Child `i` uses hint `i % 3`
   (off-by-one / edge cases / re-read tests) at temperature 0.8 to force diverse fixes.
3. All children are proposed and tested concurrently. Each scores
   `passed/total - 0.001 * min(changed_lines, 50)`, so smaller patches win ties.
4. Stop as soon as a node passes every test, else keep the top `BEAM` and repeat.

A crashing proposer or sandbox only zeroes that one node; the search keeps going.

## HTTP API

All routes except `/health` require `X-Agent-Secret: <AGENT_SHARED_SECRET>` (401 otherwise).

| Method | Path | Result |
|---|---|---|
| GET | `/health` | `{"status":"ok","mode":"fake"}` |
| GET | `/bugs` | `[{id,title,issue}]` |
| POST | `/runs` | body `{bug_id, user_id?, model_override?, replay?}` → `{run_id, mode}` |
| GET | `/runs/{id}/events` | Server-Sent Events stream (below) |
| GET | `/runs/{id}` | `{run_id, bug_id, mode, status, events}` |
| POST | `/runs/{id}/pr` | opens a PR with the winning fix → `{url}`; 400 if unsolved |
| GET | `/replays` | saved solved `hybrid`/`live` runs, best first |
| POST | `/replays/{run_id}` | re-stream a saved run → `{run_id, mode:"replay", replay_of}` |

`POST /runs` with `"replay": true` picks the best saved real run for that bug and re-streams it
(~0.3s per event, no LLM or sandbox calls); with nothing saved it falls back to a `fake` run.

### Event stream

Each message is `data: {"type": "...", "data": {...}}\n\n`:

- `node` — a tested candidate: `{id, parent, depth, idea, code, output, passed, total, score, model}`
- `round` — `{depth}` when a new round starts
- `done` — `{solved, best, usage}` (`usage`: `calls`, `prompt_tokens`, `completion_tokens`)
- `error` — `{message}` if the run itself failed
- `end` — always last; close the stream

Events already logged are replayed first, so a client can connect late.

### Completion callback

When a run finishes (success or error) it is saved to `runs/<id>.json` and the agent POSTs to
`{BACKEND_CALLBACK_URL}/internal/runs/{run_id}/complete` with header `X-Agent-Secret`:

```json
{"run_id": "...", "user_id": "...", "bug_id": "cart", "mode": "fake",
 "solved": true, "best_node_id": 4, "nodes": [...], "usage": {...}}
```

Failures are logged and ignored, so the Go endpoint is optional.

## Calling it from Go

1. `POST http://agent:8001/runs` with `X-Agent-Secret` and `{"bug_id": "...", "user_id": "<jwt subject>"}`.
2. Proxy `GET /runs/{run_id}/events` to the browser as `text/event-stream`, flushing after each
   line (the agent sends `Cache-Control: no-cache` and `X-Accel-Buffering: no`).
3. Implement `POST /internal/runs/{run_id}/complete`, check `X-Agent-Secret` with a
   constant-time compare, and store the payload in Mongo.
4. Optionally expose "Open PR" by calling `POST /runs/{run_id}/pr`.

Never expose the agent or its secret to the browser.

## Scripts

Run from `agent/`; each loads `.env`.

| Script | What it does |
|---|---|
| `scripts/01_hello_llm.py` | lists Nemotron models and asks one to say hello |
| `scripts/02_hello_sandbox.py` | runs `python --version` in a Nebius Sandbox |
| `scripts/03_fork_spike.py` | proves checkpoint forks are isolated |
| `scripts/04_check_bugs.py` | buggy < partial < correct pass counts for every bug |
| `scripts/05_run_fake.py [bug]` | full fake-mode search, prints the tree |
| `scripts/06_benchmark.py [N] [--live] [--model ID]` | single-shot vs search, solved counts and tokens |

## Tests

```bash
pytest -q
```
