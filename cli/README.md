# patchloop CLI

Start PatchLoop runs from your terminal and watch the agents' search tree live. The tests decide
which fix wins; agents can never merge: a human reviews and merges the pull request.

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

## The repo flow

```bash
patchloop login --token plk_xxxxxxxx --api http://localhost:8080
patchloop doctor                         # API reachable? logged in? GitHub? Slack?
patchloop connect github                 # opens the GitHub App install page, waits until you finish
patchloop repos                          # repos you granted to the App
patchloop fix --repo octo/widgets "pagination returns the wrong last page"
patchloop merge <run-id>                 # you merge, with your own GitHub permissions
patchloop changes <run-id> "also handle page 0"   # one more commit on the same PR
```

No GitHub App configured, or no network? `patchloop connect github --demo` connects an offline
demo account with three bundled repos (`demo/shop-api`, `demo/wordstats`,
`demo/booking`); PRs and merges there are clearly labelled fake.

`fix --repo` prints a live tree: repo scan, located files, the reproducer test (accepted only if it
fails on the original code), each round's candidates with tests passed, the verdict and the PR
link, with a spinner while it waits. The PR URL is the last stdout line (`PR: https://...`), the
rest of the chatter goes to stderr, so `url=$(patchloop fix ... | tail -1)` works.

Exit codes of `fix`/`changes`: **0** solved, **1** not solved, **2** error (API error, not
connected, rate limited, stream died). Errors print a `hint:` with the next command to run.
Ctrl-C closes only the stream (exit 130); resume with `patchloop watch <run-id>`.

`merge` shows the PR state and its checks, refuses (exit 1, with the reason) unless the PR is
open, mergeable and checks are green (a repo with no CI is allowed, with a warning), asks for
confirmation (skip with `--yes`) and merges as **you**: the agents have no merge ability.

## Any task, not just bugs (swarm)

```bash
patchloop do --repo octo/widgets --type ui "make the header responsive"
patchloop do --repo octo/widgets --strict vision_rubric --limits workers=4,tokens=500000,wall=600 "add percentage coupons"
patchloop artifacts <run> --save ./artifacts     # screenshots, logs, reports
patchloop answer <run> "1: the cart module"      # when a run needs input
```

`do` is `fix` for any task type (`--type auto|bugfix|feature|refactor|ui|tests|perf|deps|docs|migration|other`).
On a terminal you get a live frame (plan, criteria and gate table, agent lanes, merge, budget); in pipes, one line per event.
Exit codes: 0 complete, 3 partial, 1 failed/blocked, 2 error, 4 needs input. The PR URL is the last stdout line.

## Commands

| Command | What it does |
|---|---|
| `patchloop login --token plk_... [--api URL]` | verify and save a token |
| `patchloop whoami` | show the account behind the token |
| `patchloop doctor [--json]` | check API, login, GitHub, Slack; exit 1 if something needed is broken |
| `patchloop status [--json]` | API, GitHub and Slack at a glance |
| `patchloop connect github [--demo] [--no-open]` | install the GitHub App (or use the demo account) |
| `patchloop repos [--q text] [--json]` | repos PatchLoop can work on |
| `patchloop fix --repo owner/name [--branch b] [--no-pr] [--json] "problem"` | fix a bug in a repo and open a PR |
| `patchloop fix <bug-id> [--engine graph\|loop] [--replay] [--json]` | the bundled-bug demo flow |
| `patchloop merge <run-id> [--yes] [--method squash\|merge\|rebase] [--json]` | merge the run's PR as you |
| `patchloop changes <run-id> "message"` | ask for changes: a new commit on the same PR |
| `patchloop pr <run-id> [--status]` | open the PR for a solved run, or show its checks |
| `patchloop runs` | your recent runs (repo, source, status, PR) |
| `patchloop watch <run-id> [--json]` | stream an existing run (replays past events first) |
| `patchloop slack link` | one-time code; then run `/patchloop link <code>` in Slack |
| `patchloop slack set <url> \| test \| clear` | per-user incoming webhook for completion messages |
| `patchloop completion bash\|zsh\|fish\|powershell` | shell completion |

`--json` prints machine-readable output (raw events, one per line, for streams).
Colour and the spinner are off when `NO_COLOR` is set, `TERM=dumb` or output is not a terminal.

## Bundled-bug example

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

## Tests

```bash
go test ./...
```
