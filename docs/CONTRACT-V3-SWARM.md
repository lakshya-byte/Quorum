# PatchLoop contract v3: task-adaptive agent swarms (OVERRIDES v1/v2 where it conflicts)

Problem: PatchLoop only works when a failing test can be written ("improve the UI" ended as `error stage=repro`).
Goal: ANY engineering task on ANY size of repo — bug fix, feature, refactor, UI work, tests, perf, deps, migration, docs —
handled by a swarm spawned to fit the task, everything executed in sandboxes, success decided by deterministic
verifiers that the swarm synthesizes per task. LLMs write code and write verifiers; **plain code decides**. Humans merge.

## 1. Success model (replaces "all tests pass")
Every run has a `Plan.criteria` list. Each criterion has a `kind`, a `verifier`, and `hard: bool`.
HARD gates (all must pass for outcome `complete`):
- `build` : install + build/compile/typecheck succeed in the sandbox (language-aware; skip when the repo has none, status `skip`).
- `no_regression` : every test that passed on the ORIGINAL passes now (relative baseline, so repos with failing suites still work).
- `policy` : path policy (no `.github/`, no edits/deletes/weakening of EXISTING tests unless task_type=tests, no path escape, ≤ max files), `security` : bandit/semgrep-style scan no new high findings, `secrets` : no secret-looking strings added.
- type-specific synthesized hard gates:
  - bugfix: reproducer test fails on original, passes now (as today).
  - feature: acceptance tests written FIRST by a spec-test agent from the task; must fail (or not exist) on original and pass now.
  - refactor: characterization tests generated against the ORIGINAL (must pass before and after) + public API surface unchanged (exported symbols/signatures diff) + lint/typecheck no worse + at least one measurable improvement metric (file/function size, duplication, cyclomatic complexity, import cycles) when the task states one.
  - ui: build ok, no console errors on load, no horizontal overflow at 375/768/1280 px, accessibility violations (axe-core) not increased, key-flow smoke script (agent-written, run before AND after; must pass both) passes.
  - tests/perf/deps/docs/migration/other: planner must synthesize at least one executable hard verifier (command exit code, benchmark threshold, lockfile/audit result, link checker, build) — never "no test possible". If truly nothing executable exists, hard gates are only build/no_regression/policy/security, outcome is `partial`, and the PR says so.
ADVISORY criteria (never gate, always reported): vision/rubric scores of before/after screenshots, readability review, plan-adherence review. Advisory = `status:"advisory"`, with score + rationale. `strict:true` on the task promotes named advisory criteria to hard.
Outcomes: `complete` (all hard pass) | `partial` (hard gates pass but some user-stated criteria had no executable verifier, or only a subset of units landed) | `failed` | `needs_input` (planner needs a clarification; emits `clarify`) | `blocked` (guard/policy). NEVER decline a task for "not testable".

## 2. Swarm architecture (LangGraph; in `agent/app/swarm/`)
Roles (spawned dynamically; the Plan decides counts): `planner`, `mapper` (repo map: tree, languages, symbol index, import graph, test map; deterministic code, no LLM), `spec` (writes acceptance/characterization/smoke tests and ui checks), `worker` (tool-using coder, one per unit variant), `integrator` (merges unit diffs, resolves conflicts), `verifier` (deterministic runner, not an LLM), `critic` (reads failed verifier output, writes targeted repair guidance per unit), `reviewer` (PR text), `guard` (input/output). Existing bug-fix graph stays as the `bugfix` strategy for small single-cause bugs when the planner chooses it (cheap path); everything else uses the swarm.
Flow: guard → mapper ∥ baseline (build+tests on original in sandbox) → planner (task_type, criteria, units DAG, swarm sizing) → spec agents (write verifier tests/scripts, validated: must run, and per type fail/pass as above) → scheduler runs ready units (deps satisfied) in parallel: each unit gets k worker variants (k from risk, default 1-3, different strategies) in separate sandbox forks; first variant whose unit-level checks pass wins, others are cancelled → integrator merges winning unit diffs on a fresh fork (3-way; file-scope locks prevent most conflicts; real conflicts go to integrator agent) → full verification (all criteria) → if hard gates fail, critic produces repair units targeting the failing criteria → next round (max rounds, budgets) → reviewer → output guard → PR (one commit PER UNIT on the branch so reviewers can read it incrementally).
Scale for large repos: repo map + symbol/ripgrep tools instead of dumping files; workers see only unit scope files + map slices; test-impact selection (run affected tests per unit, full suite at integration); sparse upload of big repos (size/file caps from env, skip vendor/binary/lock/generated), stage checkpoints persisted so a run can resume; per-run budgets `SWARM_MAX_WORKERS` (8), `SWARM_MAX_TOKENS`, `SWARM_MAX_WALL_S`, per-worker `SWARM_WORKER_MAX_STEPS`. Planner proposes, scheduler enforces caps (never trust model-requested sizes).
Worker tools (all executed against a sandbox Workspace, never on the agent host): `list_dir`, `read_file(path, start?, end?)`, `search(regex, glob?)`, `symbols(path_or_query)`, `write_file(path, content)` / `apply_patch(path, unified_diff)` (only inside unit scope + new files; policy-checked on every call), `run(cmd)` (allow-list of project tools: test runners, build, lint, formatters, package install; no network tools like curl, no shell pipes to sh), `finish(summary)`. Tool-calling via LangChain `bind_tools` on the OpenAI-compatible Nebius client; if the model/endpoint does not support tool calls (unverified here), fall back to a JSON action loop (`{"tool":..., "args":...}`) with the same tool set. Models via env (`MODEL_NANO`, `MODEL_SUPER`; planner/integrator/critic use Super, workers Nano first then Super).
Sandbox: `Workspace` protocol (see §6). Live: Nebius Sandboxes (Contree): one checkpoint image per repo, fork per worker/verifier. Dev/fake: local temp-dir isolated subprocess (minimal env, no secrets), refused for non-demo repos unless `ALLOW_LOCAL_REPO_EXEC=1`, labelled `isolation:"local"` in events. Node/UI work uses images from env (`NODE_IMAGE` default node:20-slim, `UI_IMAGE` for chromium); unverified whether the platform can pull them; local mode uses the host's Playwright/chromium when present, else UI visual criteria report `skip` with reason.
Fake mode (offline, labelled): a scripted `FakeSwarm` replays deterministic tool-call sequences against the REAL Workspace and REAL verifiers (so builds, tests, screenshots, axe actually run) for the bundled demo repos/tasks; only the LLM is scripted.

## 3. Agent API (additions; header X-Agent-Secret as today)
`POST /repo-runs` body adds: `task_type: "auto"|"bugfix"|"feature"|"refactor"|"ui"|"tests"|"perf"|"deps"|"docs"|"migration"|"other"` (default auto), `strict: string[]` (advisory criteria ids to promote), `limits: {max_workers?, max_tokens?, max_wall_s?}` (clamped by env caps), `answers: {question_id: text}` (for needs_input follow-ups). Response unchanged. `GET /runs/{id}/artifacts` → `[{id,kind,label,phase,viewport,mime,size}]`, `GET /runs/{id}/artifacts/{artifact_id}` → bytes (png/txt/html), size cap 5 MB each, 40 per run, never contains secrets (log text passes the redactor).
## 4. SSE events (new; old events `repo, guard, locate, repro, triage, round, node, critic, done, error, pr` stay for compatibility and are still emitted by the swarm where meaningful)
- `plan` `{task_type, task_type_source:"auto"|"user", summary, criteria:[{id,kind,hard,description,verifier}], units:[{id,title,scope_files,depends_on,variants,role}], swarm:{max_parallel,workers_planned,limits}}`
- `clarify` `{questions:[{id,text}]}` then `done{outcome:"needs_input"}`
- `agent` `{id, role, unit_id|null, variant|null, status:"spawned|running|done|failed|cancelled", model, isolation:"nebius"|"local", summary?, tokens?, steps?}`
- `tool` `{agent_id, name, target?, ok, ms, note?}` (compact, ≤ 200 chars, no file contents; rate-limited to the 60 most recent per agent in replay)
- `unit` `{id, status:"pending|running|passed|failed|cancelled|merged", winner_variant?, files:[...], diff?(≤20k), checks?}`
- `merge` `{status:"ok|conflict|resolved|failed", units:[ids], conflicts:[paths]}`
- `verify` `{round, results:[{criterion_id, kind, hard, status:"pass|fail|skip|advisory", score?, detail(≤500 chars), artifacts:[ids]}], hard_pass: bool, summary:{pass,fail,skip,advisory}}`
- `artifact` `{id, kind:"screenshot|log|report|diff", label, phase:"before|after|n/a", viewport?, mime}`
- `budget` `{tokens_used, tokens_limit, wall_s, wall_limit_s, workers_active}` (every ≤2 s while running)
- `done` `{solved(bool = outcome=="complete"), outcome, task_type, best:<node with files,diff>, criteria:{hard_pass,hard_total,advisory:[...]}, usage, safety, latency_ms, time_to_first_event_ms, agents:{spawned,peak_parallel}}`
- `pr` unchanged (+`commits:n`).
First event within ~2 s (`repo` or `plan` placeholder `status` event), progress visible throughout.

## 5. Backend & CLI & Slack
Task create: `POST /api/tasks` accepts `taskType` (default `auto`), `strict`, `limits` (clamped), stores `taskType`, `outcome`, `plan` (criteria+units as sent), `criteriaSummary`, `agentsSpawned`, `peakParallel`, `artifacts[]` index; new `needs_input` flow: `POST /api/runs/:id/answers {answers}` re-runs with `answers`. Artifacts: `GET /api/runs/:id/artifacts` and `/artifacts/:artifactId` (auth + owner check, proxied from agent with the shared secret, content-type allow-list png/jpeg/svg+xml→served as attachment-safe/`text/plain`/`application/json`, `X-Content-Type-Options: nosniff`, CSP sandbox). Slack: root message shows task type + criteria table counts; per-round thread updates mention units/agents; final message adds outcome (Complete/Partial/Needs input), hard gates passed N/M, advisory notes, and the same Review/Merge/Ask-for-changes buttons (Merge only allowed per v2 rules; `partial` shows a warning). GitHub triggers: label `patchloop` + optional labels `patchloop:feature|refactor|ui|bugfix` set task type. Run model/dto: all fields camelCase in JSON. Completion callback carries `task_type, outcome, criteria, agents, plan`.
CLI: `patchloop do --repo owner/name [--type auto|bugfix|feature|refactor|ui|...] [--strict id,..] "task"` (alias of `fix`; `fix` keeps working and defaults type=auto), live swarm view (plan, agent lanes with spinners, verifier gate table, merge status), `patchloop artifacts <run> [--open|--save dir]`, `patchloop answer <run> "text"`, exit codes: 0 complete, 3 partial, 1 failed, 2 error, 4 needs_input.
## 6. Interfaces the agent-side builders share (names are binding)
```python
# agent/app/swarm/workspace.py  (owner: sandbox/verifier builder)
class Workspace(Protocol):
    isolation: str                                  # "nebius" | "local"
    async def list_dir(self, path: str = ".") -> list[str]
    async def read(self, path: str, start: int | None = None, end: int | None = None) -> str
    async def write(self, path: str, text: str) -> None            # raises PolicyError outside allowed scope
    async def search(self, pattern: str, glob: str | None = None, limit: int = 50) -> list[tuple[str, int, str]]
    async def exec(self, cmd: str, timeout: int = 120) -> ExecResult   # (code, stdout_tail, duration_ms); allow-listed
    async def changed(self) -> dict[str, str | None]               # path -> new text (None = deleted) vs checkpoint
    async def fork(self) -> "Workspace"                            # cheap copy of current state
    async def release(self) -> None
class WorkspaceFactory(Protocol):
    async def open(self, files: dict[str, str], *, language_hint: str | None) -> Workspace   # one checkpoint, forks after
# agent/app/swarm/verifiers/__init__.py  (owner: sandbox/verifier builder)
@dataclass class Criterion: id, kind, hard, description, params: dict
@dataclass class VerifyResult: criterion_id, kind, hard, status, score: float|None, detail: str, artifacts: list[Artifact]
async def run_verifier(c: Criterion, ws: Workspace, baseline: "Baseline", artifacts: ArtifactStore) -> VerifyResult
async def collect_baseline(ws: Workspace, repo_map: "RepoMap") -> "Baseline"      # build status, passing test ids, axe counts...
def build_repo_map(files: dict[str, str]) -> "RepoMap"                                # deterministic; tree, langs, symbols, imports, tests, entrypoints, build/test commands
class ArtifactStore: add(kind,label,phase,viewport,mime,data)->Artifact ; list() ; get(id)
# agent/app/swarm/engine.py  (owner: swarm-core builder) : async def run_swarm(ctx: SwarmCtx) -> Node
```
## 7. Frontend
`/new`: task-type chips (Auto default, Bug fix, Feature, Refactor, UI/UX, Tests, Performance, Dependencies, Docs, Other) each with an honest one-line "how it's verified" and example prompts; optional limits drawer. Run page = **Swarm view**: Plan card (type, criteria with hard/advisory chips), agent lanes (one lane per unit, variants as sub-rows, live status + last tool, budget meter), Verification gate table (per criterion pass/fail/skip/advisory with detail), Merge panel, Artifacts gallery (before/after screenshot slider/side-by-side per viewport, logs), diff viewer per unit and combined, PR card (outcome chip: Complete/Partial/Needs input; Merge per v2 rules), needs-input answer form. Bug-fix runs keep the old compact view. Landing copy updated truthfully: "Describe a bug, a feature, a refactor or a UI change. PatchLoop spawns a swarm sized to the task, runs everything in sandboxes, and only opens a PR when its own checks pass. You merge." No claims about model quality or scale you cannot show; the scale claim is "designed for large repos: repo map, sparse context, budgets", flagged honestly.
Mocks (`frontend/mocks`) implement every new endpoint and a full swarm stream for a UI task and a refactor task incl. artifacts (generated PNG/SVG).
## 8. Evals (phase 2, after merge)
Golden dataset gets feature/refactor/ui/tests/needs_input cases and swarm metrics: outcome_match, criteria_verifiability, hard_gate_pass, decomposition_quality (unit scope overlap, coverage), parallel_efficiency, budget_adherence, no_decline_rate (task must never be declined for 'not testable'), advisory vs hard separation.
## 9. Definition of done (all sides)
All suites green; in fake mode with demo repos the e2e shows: UI task -> plan with hard/advisory criteria -> parallel workers -> real before/after screenshots -> verify gates -> PR with commit per unit; a feature task (tests-first); a refactor task (characterization tests + API surface check); the old bug-fix path still works; a vague task triggers `clarify`; caps enforced; workers can never touch tests/.github/outside scope; no secrets in logs/artifacts. Unverified list names every live dependency (Nebius tool-calling, sandbox images, chromium image).
