# patchloop CLI

Start PatchLoop runs from your terminal and watch the agents' search tree live. The tests decide
which fix wins; agents can never merge. `patchloop pr` opens a PR for a human to review.

## Install

```bash
cd cli
go install ./cmd/patchloop        # puts `patchloop` in $(go env GOPATH)/bin
# or
go build -o patchloop ./cmd/patchloop
```

Go 1.27+.

## Log in

Create an API token in the web app (or `POST /api/tokens {"name":"laptop"}` while signed in;
the plaintext `plk_...` value is shown once), then:

```bash
patchloop login --token plk_xxxxxxxx --api http://localhost:8080
patchloop whoami
```

The token is checked against `/api/auth/me` and saved to `~/.config/patchloop/config.json`
(mode 0600; `$XDG_CONFIG_HOME` is honoured, `PATCHLOOP_CONFIG` overrides the path).
`--api` or `PATCHLOOP_API` override the saved backend URL for one command.

## Commands

| Command | What it does |
|---|---|
| `patchloop login --token plk_... [--api URL]` | verify and save a token |
| `patchloop whoami` | show the account behind the token |
| `patchloop bugs` | list bugs |
| `patchloop fix <bug-id> [--engine graph\|loop] [--replay] [--json]` | start a run and stream it; exit 0 if solved, 1 if not |
| `patchloop runs` | your recent runs |
| `patchloop watch <run-id> [--json]` | stream an existing run (replays past events first) |
| `patchloop pr <run-id>` | open a GitHub PR with the winning fix, prints its URL |

## Example

```
$ patchloop fix cart --engine graph
run 6a1f... started (mode=live engine=graph)
PatchLoop run 3be1c0d2  bug=cart mode=live engine=graph
◆ guard input  pass (12ms)
◇ triage: quantity is ignored when summing
  strategies: multiply by qty | edge cases | re-read tests
── round 0 ──
  ├─ #0 [2/6] original code  (nemotron-nano, 900ms, 400 tok)
── round 1 ──
    ├─ #1 [5/6] multiply price by quantity  (...)
    ├─ #2 [3/6] handle empty cart  (...)
  ✎ critic on #2: empty carts already work; focus on quantity
── round 2 ──
      ├─ #4 [6/6] round to cents after summing  (...)
◆ guard policy pass (8ms)
✓ SOLVED  best #4 6/6 tests
  tokens 4000 (prompt 3120 + completion 880) · latency 4.2s · first node 350ms
$ echo $?
0
```

Nodes are indented by depth and coloured by tests passed: green = all, amber = some, red = none.
Colour is off when `NO_COLOR` is set, `TERM=dumb`, or output is not a terminal.

`--json` prints each raw event (`{"type":...,"data":{...}}`) on its own line, e.g.
`patchloop fix cart --json | jq -c 'select(.type=="node") | .data.passed'`.

**Ctrl-C** closes the stream only (exit 130); the run keeps going on the server. Resume with
`patchloop watch <run-id>`.

## Tests

```bash
go test ./...
```
