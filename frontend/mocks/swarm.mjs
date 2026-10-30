// Scripted swarm runs for the mock backend (contract v3 events). Everything here is invented
// for the UI: no model, no sandbox. Scenarios: ui, feature, refactor, partial (docs/perf/other),
// unsolvable (honest failure), needs_input (clarify), followup.

import { unifiedDiff } from "./repos.mjs";
import { axeReport, logText, todoShot } from "./artifacts.mjs";

export const UI_REPO = {
  fullName: "demo/react-todo",
  description: "A basic React todo app (Vite). Demo repo for UI tasks, mock backend only.",
  language: "JavaScript",
  files: { "src/App.jsx": "export default function App() {}\n", "src/App.css": "body { font-family: serif; }\n", "package.json": "{}\n" },
  locate: [{ path: "src/App.jsx" }, { path: "src/App.css" }, { path: "src/components/TodoList.jsx" }],
};

const NANO = "nemotron-nano (Nebius Token Factory)";
const SUPER = "nemotron-super (Nebius Token Factory)";

// ---------- classification (mock stand-in for the planner) ----------
export function classify(task, userType, answered) {
  const t = task.toLowerCase();
  if (/unsolvable|impossible|delete (all |the )?tests|make the tests pass by/.test(t)) return { type: userType && userType !== "auto" ? userType : "feature", source: userType && userType !== "auto" ? "user" : "auto", kind: "unsolvable" };
  const user = userType && userType !== "auto";
  let type = null;
  if (/\b(ui|ux|css|style|styling|design|layout|responsive|look)\b/.test(t)) type = "ui";
  else if (/refactor|split|restructure|extract|monolith|clean ?up/.test(t)) type = "refactor";
  else if (/\b(docs?|readme|document|guide)\b/.test(t)) type = "docs";
  else if (/\b(tests?|coverage)\b/.test(t) && /\b(add|write|increase)\b/.test(t)) type = "tests";
  else if (/\b(slow|perf|performance|speed up|faster|latency)\b/.test(t)) type = "perf";
  else if (/\b(upgrade|dependenc|bump|migrat)/.test(t)) type = "deps";
  else if (/\b(add|implement|feature|support|introduce|tiers?)\b/.test(t)) type = "feature";
  else if (/\b(bug|fix|wrong|error|crash|fails?|incorrect|broken|doesn't|does not)\b/.test(t)) type = "bugfix";
  if (user) type = userType;
  if (!type && !answered && (t.length < 24 || /^(make it better|improve it|fix it|do something|help)/.test(t))) return { type: "other", source: "auto", kind: "needs_input" };
  if (!type) type = "other";
  const kind = ["ui", "feature", "refactor"].includes(type) ? type : type === "bugfix" ? "bugfix" : "partial";
  return { type, source: user ? "user" : "auto", kind };
}

// ---------- timeline builder ----------
class TL {
  constructor() {
    this.ev = [];
    this.tokens = 0;
    this.n = 0;
  }
  at(t, type, data) {
    this.ev.push({ at: Math.round(t), type, data, n: this.n++ });
  }
  agent(t, id, role, status, extra = {}) {
    this.at(t, "agent", { id, role, unit_id: null, variant: null, model: role === "mapper" ? "code (no model)" : extra.model ?? SUPER, isolation: "local", ...extra, status });
  }
  /** a worker-ish lane: spawn, run, tool calls, end. Returns end time. */
  lane(start, id, role, unit, variant, tools, end, summary, model = NANO) {
    const base = { unit_id: unit, variant, model };
    this.agent(start, id, role, "spawned", base);
    this.agent(start + 90, id, role, "running", base);
    const gap = (end.at - start - 200) / Math.max(1, tools.length);
    tools.forEach(([name, target, ok = true, note], i) => {
      this.at(start + 200 + gap * (i + 0.5), "tool", { agent_id: id, name, target, ok, ms: 40 + ((i * 97) % 900), ...(note ? { note } : {}) });
    });
    const tokens = 2100 + tools.length * 640;
    this.tokens += tokens;
    this.agent(end.at, id, role, end.status, { ...base, summary, tokens, steps: tools.length });
    return end.at;
  }
  sorted(withBudget = true) {
    const ev = [...this.ev].sort((a, b) => a.at - b.at || a.n - b.n);
    if (!withBudget) return ev.map(({ n, ...e }) => (void n, e));
    const active = new Set();
    let tokens = 0;
    const out = [];
    const endAt = ev[ev.length - 1].at;
    let nextTick = 700;
    for (const e of ev) {
      while (nextTick < e.at) {
        out.push({ at: nextTick, type: "budget", data: { tokens_used: tokens, tokens_limit: 400000, wall_s: Math.round(nextTick / 100) / 10, wall_limit_s: 600, workers_active: active.size } });
        nextTick += 1500;
      }
      if (e.type === "agent") {
        const run = e.data.status === "running" || e.data.status === "spawned";
        if (run && e.data.role !== "mapper") active.add(e.data.id);
        else active.delete(e.data.id);
        if (e.data.tokens) tokens += e.data.tokens;
      }
      out.push({ at: e.at, type: e.type, data: e.data });
    }
    out.push({ at: endAt, type: "budget", data: { tokens_used: tokens, tokens_limit: 400000, wall_s: Math.round(endAt / 100) / 10, wall_limit_s: 600, workers_active: 0 } });
    return out.sort((a, b) => a.at - b.at).map((e) => e);
  }
}

let artSeq = 0;
function art(list, meta, gen) {
  const id = `a${++artSeq}${Math.random().toString(36).slice(2, 6)}`;
  list.push({ meta: { id, size: 0, ...meta }, gen });
  return id;
}

function summarize(results) {
  const c = { pass: 0, fail: 0, skip: 0, advisory: 0 };
  for (const r of results) c[r.status]++;
  return c;
}
const R = (criterion_id, kind, hard, status, detail, extra = {}) => ({ criterion_id, kind, hard, status, detail, artifacts: [], ...extra });

function planCommon(type, source, summary, specific, extraAdvisory, units, workersPlanned, strict = []) {
  const criteria = [
    { id: "build", kind: "build", hard: true, description: "Install and build/compile succeed in the sandbox", verifier: "command exit code" },
    { id: "no_regression", kind: "no_regression", hard: true, description: "Every test that passed on the original still passes", verifier: "relative baseline test diff" },
    { id: "policy", kind: "policy", hard: true, description: "No .github/ edits, no edits to existing tests, files within limits", verifier: "path policy" },
    { id: "security", kind: "security", hard: true, description: "No new high-severity findings", verifier: "static scan" },
    { id: "secrets", kind: "secrets", hard: true, description: "No secret-looking strings added", verifier: "pattern scan" },
    ...specific,
    ...extraAdvisory,
  ].map((c) => (strict.includes(c.id) ? { ...c, hard: true } : c));
  return {
    task_type: type,
    task_type_source: source,
    summary,
    criteria,
    units,
    swarm: { max_parallel: 4, workers_planned: workersPlanned, limits: { max_workers: 8, max_tokens: 400000, max_wall_s: 600 } },
  };
}

function head(tl, repo, branch, files, lang, testCmd) {
  tl.at(0, "run_started", { run_id: null, bug_id: "", mode: "fake", engine: "swarm" });
  tl.at(120, "repo", { full_name: repo.fullName, branch, files, language: lang, test_command: testCmd, truncated: false });
  tl.at(200, "guard", { stage: "input", verdict: "pass", reasons: [], latency_ms: 91 });
  tl.agent(260, "mapper", "mapper", "spawned");
  tl.agent(300, "mapper", "mapper", "running");
  tl.at(520, "tool", { agent_id: "mapper", name: "repo_map", target: `${files} files, symbols, import graph`, ok: true, ms: 210 });
  tl.agent(900, "mapper", "mapper", "done", { summary: "Repo map built: tree, symbols, import graph, test map." });
  tl.lane(300, "planner", "planner", null, null, [["list_dir", "."], ["read_file", "package.json"], ["symbols", "entrypoints"], ["search", "TODO|FIXME"]], { at: 1500, status: "done" }, "Classified the task, synthesized criteria, sized the swarm.", SUPER);
}

function tail(tl, t, { outcome, taskType, best, hard, hardTotal, advisory, spawned, peak, usage, pr, extraCriteria = {}, prNumber }) {
  tl.at(t, "guard", { stage: "output", verdict: "pass", reasons: [], latency_ms: 118 });
  tl.at(t + 200, "done", {
    solved: outcome === "complete",
    outcome,
    task_type: taskType,
    best,
    criteria: { hard_pass: hard, hard_total: hardTotal, advisory, ...extraCriteria },
    usage: { prompt_tokens: Math.round(usage * 0.8), completion_tokens: Math.round(usage * 0.2) },
    latency_ms: t + 200,
    time_to_first_event_ms: 180,
    agents: { spawned, peak_parallel: peak },
  });
  if (pr) tl.at(t + 700, "pr", { url: `https://github.com/${pr.repo}/pull/${prNumber}`, branch: pr.branch, number: prNumber, fake: true, commits: pr.commits });
  tl.at(t + (pr ? 740 : 260), "end", {});
}

const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 28);

// ---------- scenario: UI ----------
function uiScenario(c) {
  const tl = new TL();
  const arts = [];
  head(tl, c.repo, c.branch, 11, "javascript", "npm test");
  const units = [
    { id: "u1", title: "Design tokens and base styles", scope_files: ["src/App.css"], depends_on: [], variants: 2, role: "worker" },
    { id: "u2", title: "Restyle the todo list and form", scope_files: ["src/components/TodoList.jsx", "src/components/AddTodo.jsx"], depends_on: ["u1"], variants: 2, role: "worker" },
    { id: "u3", title: "Responsive layout and labels", scope_files: ["src/App.jsx", "index.html"], depends_on: ["u1"], variants: 1, role: "worker" },
  ];
  const plan = planCommon(
    "ui",
    c.source,
    "Improve the visual design and responsiveness of the todo app without changing behavior. Hard gates are mechanical; the visual judgement is advisory.",
    [
      { id: "ui_console", kind: "console_errors", hard: true, description: "No console errors on page load", verifier: "headless browser" },
      { id: "ui_overflow", kind: "no_overflow", hard: true, description: "No horizontal overflow at 375, 768 and 1280 px", verifier: "headless browser" },
      { id: "ui_axe", kind: "a11y_axe", hard: true, description: "axe-core violations do not increase", verifier: "axe-core before vs after" },
      { id: "ui_smoke", kind: "smoke", hard: true, description: "Key flow: add, complete and delete a todo (script run before AND after)", verifier: "agent-written script" },
    ],
    [
      { id: "ui_vision", kind: "vision_rubric", hard: false, description: "Hierarchy, spacing and contrast improved (vision rubric on before/after screenshots)", verifier: "model rubric" },
      { id: "ui_readability", kind: "readability_review", hard: false, description: "Diff is readable and follows the repo's conventions", verifier: "model review" },
      { id: "plan_adherence", kind: "plan_adherence", hard: false, description: "Changes stay inside each unit's scope", verifier: "model review" },
    ],
    units,
    5,
    c.strict
  );
  tl.at(1500, "plan", plan);
  const before = [375, 768, 1280].map((v) => art(arts, { kind: "screenshot", label: "Todo page", phase: "before", viewport: v, mime: "image/png" }, () => todoShot(v, "before")));
  void before;
  tl.lane(1600, "spec-1", "spec", null, null, [["read_file", "src/App.jsx"], ["write_file", "tests/ui/smoke.spec.js"], ["run", "node tests/ui/smoke.spec.js (original)"], ["write_file", "tests/ui/overflow.spec.js"], ["run", "axe-core on original"]], { at: 3300, status: "done" }, "Wrote the smoke and overflow checks and ran them against the original.", SUPER);
  [375, 768, 1280].forEach((v, i) => tl.at(2000 + i * 300, "artifact", arts.find((a) => a.meta.phase === "before" && a.meta.viewport === v).meta));
  const logId = art(arts, { kind: "log", label: "smoke script (before and after)", phase: "n/a", mime: "text/plain" }, () => Buffer.from(logText("smoke.log")));
  tl.at(3300, "artifact", arts.find((a) => a.meta.id === logId).meta);

  // u1: two strategies, first to pass wins
  tl.at(3400, "unit", { id: "u1", status: "running", files: [] });
  tl.lane(3400, "w-u1-a", "worker", "u1", "a", [["read_file", "src/App.css"], ["search", "font-family"], ["write_file", "src/App.css"], ["run", "npm run build"], ["run", "unit checks"]], { at: 5600, status: "done" }, "Tokens in :root, system font stack, spacing scale.");
  tl.lane(3400, "w-u1-b", "worker", "u1", "b", [["read_file", "src/App.css"], ["write_file", "src/App.css"], ["run", "npm run build"]], { at: 5650, status: "cancelled" }, "Cancelled: variant a passed first.");
  const d1 = unifiedDiff("src/App.css", "body { font-family: serif; }\n.todo { margin: 4px; }\ntable { width: 900px; }\n", ":root { --bg: #0f121c; --card: #181d2c; --accent: #10b981; --space: 16px; }\nbody { font-family: system-ui, sans-serif; background: var(--bg); color: #ebf0fa; }\n.todo { margin: var(--space) 0; }\n.todos { width: 100%; }\n");
  tl.at(5700, "unit", { id: "u1", status: "passed", winner_variant: "a", files: ["src/App.css"], diff: d1, checks: { build: "ok" } });
  // u2 / u3 in parallel
  tl.at(5800, "unit", { id: "u2", status: "running", files: [] });
  tl.at(5800, "unit", { id: "u3", status: "running", files: [] });
  tl.lane(5800, "w-u2-a", "worker", "u2", "a", [["read_file", "src/components/TodoList.jsx"], ["write_file", "src/components/TodoList.jsx"], ["run", "npm run build"], ["run", "axe-core unit check", false, "contrast 2.9:1 on .todo-meta"]], { at: 8200, status: "failed" }, "Failed the unit's axe check: low contrast on secondary text.");
  tl.lane(5800, "w-u2-b", "worker", "u2", "b", [["read_file", "src/components/TodoList.jsx"], ["read_file", "src/components/AddTodo.jsx"], ["write_file", "src/components/TodoList.jsx"], ["write_file", "src/components/AddTodo.jsx"], ["run", "npm run build"], ["run", "axe-core unit check"]], { at: 8900, status: "done" }, "Card list, labelled input, visible focus styles.");
  tl.lane(5800, "w-u3-a", "worker", "u3", "a", [["read_file", "src/App.jsx"], ["write_file", "src/App.jsx"], ["write_file", "index.html"], ["run", "npm run build"]], { at: 7600, status: "done" }, "Responsive container, lang and viewport meta.");
  const d3 = unifiedDiff("src/App.jsx", "export default function App() {\n  return <div><h1>My todos</h1><TodoList /></div>;\n}\n", "export default function App() {\n  return (\n    <main className=\"page\">\n      <h1>My todos</h1>\n      <TodoList />\n    </main>\n  );\n}\n");
  tl.at(7650, "unit", { id: "u3", status: "passed", winner_variant: "a", files: ["src/App.jsx", "index.html"], diff: d3 });
  const d2 = unifiedDiff("src/components/TodoList.jsx", "export function TodoList({ items }) {\n  return <table>{items.map((i) => <tr><td>{i.text}</td></tr>)}</table>;\n}\n", "export function TodoList({ items }) {\n  return (\n    <ul className=\"todos\">\n      {items.map((i) => (\n        <li className=\"todo\" key={i.id}>{i.text}</li>\n      ))}\n    </ul>\n  );\n}\n");
  tl.at(8950, "unit", { id: "u2", status: "passed", winner_variant: "b", files: ["src/components/TodoList.jsx", "src/components/AddTodo.jsx"], diff: d2 });
  // merge with a conflict the integrator resolves
  tl.at(9100, "merge", { status: "conflict", units: ["u1", "u2", "u3"], conflicts: ["src/App.css"] });
  tl.lane(9150, "integrator", "integrator", null, null, [["read_file", "src/App.css"], ["apply_patch", "src/App.css"], ["run", "npm run build"]], { at: 10300, status: "done" }, "Resolved one overlapping hunk in src/App.css.", SUPER);
  tl.at(10350, "merge", { status: "resolved", units: ["u1", "u2", "u3"], conflicts: ["src/App.css"] });
  ["u1", "u2", "u3"].forEach((u) => tl.at(10400, "unit", { id: u, status: "merged", files: [] }));
  const buildLog = art(arts, { kind: "log", label: "build output", phase: "after", mime: "text/plain" }, () => Buffer.from(logText("build.log")));
  const ovLog = art(arts, { kind: "log", label: "overflow check, round 1", phase: "after", mime: "text/plain" }, () => Buffer.from(logText("overflow-r1.log")));
  tl.at(10900, "artifact", arts.find((a) => a.meta.id === buildLog).meta);
  tl.at(10950, "artifact", arts.find((a) => a.meta.id === ovLog).meta);
  const r1 = [
    R("build", "build", true, "pass", "vite build ok in 1.8s"),
    R("no_regression", "no_regression", true, "pass", "13 of 13 baseline tests still pass"),
    R("policy", "policy", true, "pass", "6 files changed, none under .github/ or tests/"),
    R("security", "security", true, "pass", "no new findings"),
    R("secrets", "secrets", true, "pass", "none added"),
    R("ui_console", "console_errors", true, "pass", "0 console errors on load"),
    R("ui_overflow", "no_overflow", true, "fail", "375px: scrollWidth 612 > 375 (table.todos overflows by 237px)", { artifacts: [ovLog] }),
    R("ui_axe", "a11y_axe", true, "pass", "violations 5 -> 2"),
    R("ui_smoke", "smoke", true, "pass", "add, complete, delete: pass before and after"),
    R("ui_vision", "vision_rubric", false, "advisory", "Clearer hierarchy and spacing; one low-contrast label remains.", { score: 0.74 }),
    R("ui_readability", "readability_review", false, "advisory", "Small, focused diff; class names are consistent.", { score: 0.81 }),
    R("plan_adherence", "plan_adherence", false, "advisory", "All edits stayed inside unit scope.", { score: 0.9 }),
  ];
  tl.at(11000, "verify", { round: 1, results: r1, hard_pass: false, summary: summarize(r1) });
  tl.lane(11300, "critic-1", "critic", null, null, [["read_file", "overflow-r1.log"], ["read_file", "src/components/TodoList.jsx"]], { at: 12000, status: "done" }, "ui_overflow fails at 375px: the old table markup is still used in one place. Repair unit u4.", SUPER);
  tl.at(12050, "unit", { id: "u4", status: "running", files: [] });
  tl.lane(12100, "w-u4-a", "worker", "u4", "a", [["read_file", "src/components/TodoList.jsx"], ["search", "<table"], ["write_file", "src/App.css"], ["run", "overflow check 375"], ["run", "npm run build"]], { at: 14000, status: "done" }, "Replaced the last table with a list and added min-width: 0.");
  const d4 = unifiedDiff("src/App.css", ":root { --space: 16px; }\n.todos { width: 100%; }\n", ":root { --space: 16px; }\n.todos { width: 100%; min-width: 0; overflow-wrap: anywhere; }\n");
  tl.at(14050, "unit", { id: "u4", status: "passed", winner_variant: "a", files: ["src/App.css"], diff: d4 });
  tl.at(14200, "merge", { status: "ok", units: ["u4"], conflicts: [] });
  tl.at(14250, "unit", { id: "u4", status: "merged", files: [] });
  const after = [375, 768, 1280].map((v) => art(arts, { kind: "screenshot", label: "Todo page", phase: "after", viewport: v, mime: "image/png" }, () => todoShot(v, "after")));
  after.forEach((id, i) => tl.at(14500 + i * 150, "artifact", arts.find((a) => a.meta.id === id).meta));
  const axe = art(arts, { kind: "report", label: "axe-core report (after)", phase: "after", mime: "application/json" }, () => Buffer.from(axeReport("after")));
  tl.at(14950, "artifact", arts.find((a) => a.meta.id === axe).meta);
  const r2 = r1.map((r) => (r.criterion_id === "ui_overflow" ? R("ui_overflow", "no_overflow", true, "pass", "scrollWidth equals the viewport at 375, 768 and 1280", { artifacts: after }) : r.criterion_id === "ui_axe" ? R("ui_axe", "a11y_axe", true, "pass", "violations 5 -> 1", { artifacts: [axe] }) : r.criterion_id === "ui_vision" ? { ...r, score: 0.83, detail: "Clear hierarchy and consistent spacing; contrast improved." } : r));
  tl.at(15100, "verify", { round: 2, results: r2, hard_pass: true, summary: summarize(r2) });
  tl.lane(15300, "reviewer", "reviewer", null, null, [["read_file", "combined diff"], ["write_file", "PR description"]], { at: 16000, status: "done" }, "Wrote the PR description with the evidence table.", SUPER);
  const full = [d1, d2, d3, d4].join("");
  const branch = `patchloop/${slug(c.task)}-${Math.floor(Date.now() / 1000)}`;
  tail(tl, 16100, {
    outcome: "complete", taskType: "ui",
    best: { id: 1, parent: null, depth: 0, passed: 9, total: 9, score: 1, idea: "Combined swarm result", diff: full, files: { "src/App.css": "", "src/App.jsx": "", "src/components/TodoList.jsx": "", "src/components/AddTodo.jsx": "", "index.html": "" } },
    hard: 9, hardTotal: 9, advisory: r2.filter((r) => r.status === "advisory").map((r) => ({ id: r.criterion_id, score: r.score })),
    spawned: Object.keys(tl.ev.filter((e) => e.type === "agent").reduce((m, e) => ({ ...m, [e.data.id]: 1 }), {})).length, peak: 3, usage: tl.tokens, pr: c.autoPr ? { repo: c.repo.fullName, branch, commits: 4 } : null, prNumber: c.prNumber,
  });
  return { events: tl.sorted(), plan, artifacts: arts, lastVerify: r2, best: tl.ev.find((e) => e.type === "done")?.data.best };
}

// ---------- scenario: feature (tests first) ----------
function featureScenario(c) {
  const tl = new TL();
  const arts = [];
  head(tl, c.repo, c.branch, 9, "python", "python -m unittest");
  const units = [
    { id: "u1", title: "Tier table and pricing helper", scope_files: ["shop/pricing.py"], depends_on: [], variants: 2, role: "worker" },
    { id: "u2", title: "Apply tiers in Cart.total()", scope_files: ["shop/cart.py"], depends_on: ["u1"], variants: 1, role: "worker" },
    { id: "u3", title: "Document the tiers", scope_files: ["README.md"], depends_on: [], variants: 1, role: "worker" },
  ];
  const plan = planCommon(
    "feature", c.source,
    "Add quantity-based discount tiers. Acceptance tests are written first from the task text and must fail on the original code.",
    [
      { id: "acceptance", kind: "acceptance_tests", hard: true, description: "tests/test_bulk_tiers.py (written first): fails on original, passes now", verifier: "unittest, before and after" },
    ],
    [
      { id: "readability", kind: "readability_review", hard: false, description: "New code reads like the surrounding code", verifier: "model review" },
      { id: "plan_adherence", kind: "plan_adherence", hard: false, description: "Changes stay inside unit scope", verifier: "model review" },
    ],
    units, 4, c.strict
  );
  tl.at(1500, "plan", plan);
  tl.lane(1600, "spec-1", "spec", null, null, [["read_file", "shop/cart.py"], ["write_file", "tests/test_bulk_tiers.py"], ["run", "python -m unittest tests.test_bulk_tiers (original)", true, "4 failed, as required"], ["run", "validate: must fail first"]], { at: 3000, status: "done" }, "Wrote 4 acceptance tests; they fail on the original code, as required.", SUPER);
  const spec = art(arts, { kind: "log", label: "acceptance tests: original vs final", phase: "n/a", mime: "text/plain" }, () => Buffer.from(logText("spec.log")));
  tl.at(3000, "artifact", arts.find((a) => a.meta.id === spec).meta);
  tl.at(3100, "unit", { id: "u1", status: "running", files: [] });
  tl.at(3100, "unit", { id: "u3", status: "running", files: [] });
  tl.lane(3100, "w-u1-a", "worker", "u1", "a", [["read_file", "shop/coupons.py"], ["write_file", "shop/pricing.py"], ["run", "python -m unittest"]], { at: 5200, status: "done" }, "Dict-based tier table with a bisect lookup.");
  tl.lane(3100, "w-u1-b", "worker", "u1", "b", [["read_file", "shop/coupons.py"], ["write_file", "shop/pricing.py"]], { at: 5250, status: "cancelled" }, "Cancelled: variant a passed first.");
  tl.lane(3100, "w-u3-a", "worker", "u3", "a", [["read_file", "README.md"], ["write_file", "README.md"]], { at: 4300, status: "done" }, "README section on tiers.");
  const d1 = unifiedDiff("shop/pricing.py", "", "from bisect import bisect_right\n\nTIERS = [(10, 5), (50, 10), (100, 15)]  # (min qty, percent off)\n\n\ndef tier_percent(qty):\n    i = bisect_right([q for q, _ in TIERS], qty)\n    return TIERS[i - 1][1] if i else 0\n");
  const d3 = unifiedDiff("README.md", "# shop-api\n", "# shop-api\n\n## Bulk discount tiers\n\n10+ items: 5%, 50+: 10%, 100+: 15%.\n");
  tl.at(5300, "unit", { id: "u1", status: "passed", winner_variant: "a", files: ["shop/pricing.py"], diff: d1 });
  tl.at(4350, "unit", { id: "u3", status: "passed", winner_variant: "a", files: ["README.md"], diff: d3 });
  tl.at(5400, "unit", { id: "u2", status: "running", files: [] });
  tl.lane(5400, "w-u2-a", "worker", "u2", "a", [["read_file", "shop/cart.py"], ["write_file", "shop/cart.py"], ["run", "python -m unittest tests.test_bulk_tiers"], ["run", "python -m unittest"]], { at: 7600, status: "done" }, "Cart.total() applies the tier to items, never to shipping.");
  const d2 = unifiedDiff("shop/cart.py", "    def total(self):\n        items = self.subtotal()\n        return items + self.shipping()\n", "    def total(self):\n        items = self.subtotal()\n        items -= items * tier_percent(self.quantity()) // 100\n        return items + self.shipping()\n");
  tl.at(7650, "unit", { id: "u2", status: "passed", winner_variant: "a", files: ["shop/cart.py"], diff: d2 });
  tl.at(7800, "merge", { status: "ok", units: ["u1", "u3", "u2"], conflicts: [] });
  ["u1", "u2", "u3"].forEach((u) => tl.at(7850, "unit", { id: u, status: "merged", files: [] }));
  const tests = art(arts, { kind: "log", label: "full suite, original vs now", phase: "after", mime: "text/plain" }, () => Buffer.from(logText("tests.log")));
  tl.at(8200, "artifact", arts.find((a) => a.meta.id === tests).meta);
  const r = [
    R("build", "build", true, "skip", "Python project: no build step"),
    R("no_regression", "no_regression", true, "pass", "13 of 13 baseline tests still pass", { artifacts: [tests] }),
    R("policy", "policy", true, "pass", "3 files changed + 1 new test file, none under .github/"),
    R("security", "security", true, "pass", "bandit: no new findings"),
    R("secrets", "secrets", true, "pass", "none added"),
    R("acceptance", "acceptance_tests", true, "pass", "4 acceptance tests: failed on original, pass now", { artifacts: [spec] }),
    R("readability", "readability_review", false, "advisory", "Matches the surrounding style.", { score: 0.86 }),
    R("plan_adherence", "plan_adherence", false, "advisory", "Inside unit scope.", { score: 0.92 }),
  ];
  tl.at(8400, "verify", { round: 1, results: r, hard_pass: true, summary: summarize(r) });
  tl.lane(8600, "reviewer", "reviewer", null, null, [["read_file", "combined diff"], ["write_file", "PR description"]], { at: 9300, status: "done" }, "Wrote the PR description.", SUPER);
  const branch = `patchloop/${slug(c.task)}-${Math.floor(Date.now() / 1000)}`;
  const hardOk = r.filter((x) => x.hard && x.status === "pass").length;
  tail(tl, 9400, {
    outcome: "complete", taskType: "feature",
    best: { id: 1, parent: null, depth: 0, passed: 4, total: 4, score: 1, idea: "Combined swarm result", diff: [d1, d2, d3].join(""), files: { "shop/pricing.py": "", "shop/cart.py": "", "README.md": "", "tests/test_bulk_tiers.py": "" } },
    hard: hardOk, hardTotal: r.filter((x) => x.hard).length, advisory: r.filter((x) => x.status === "advisory").map((x) => ({ id: x.criterion_id, score: x.score })),
    spawned: new Set(tl.ev.filter((e) => e.type === "agent").map((e) => e.data.id)).size, peak: 3, usage: tl.tokens, pr: c.autoPr ? { repo: c.repo.fullName, branch, commits: 3 } : null, prNumber: c.prNumber,
  });
  return { events: tl.sorted(), plan, artifacts: arts, lastVerify: r, best: tl.ev.find((e) => e.type === "done")?.data.best };
}

// ---------- scenario: refactor (characterization + API surface) ----------
function refactorScenario(c) {
  const tl = new TL();
  const arts = [];
  head(tl, c.repo, c.branch, 8, "python", "python -m unittest");
  const units = [
    { id: "u1", title: "Extract tokenizer", scope_files: ["wordstats/core.py", "wordstats/tokenize.py"], depends_on: [], variants: 1, role: "worker" },
    { id: "u2", title: "Extract counter", scope_files: ["wordstats/core.py", "wordstats/counter.py"], depends_on: [], variants: 1, role: "worker" },
    { id: "u3", title: "Extract report", scope_files: ["wordstats/core.py", "wordstats/report.py"], depends_on: [], variants: 1, role: "worker" },
    { id: "u4", title: "Re-export the public API", scope_files: ["wordstats/__init__.py"], depends_on: ["u1", "u2", "u3"], variants: 1, role: "worker" },
  ];
  const plan = planCommon(
    "refactor", c.source,
    "Split wordstats/core.py into focused modules while keeping every public name and signature. Characterization tests are generated against the ORIGINAL code.",
    [
      { id: "characterization", kind: "characterization_tests", hard: true, description: "Generated characterization tests pass before and after", verifier: "unittest on original and refactor" },
      { id: "api_surface", kind: "api_surface", hard: true, description: "Exported symbols and signatures unchanged", verifier: "symbol diff" },
      { id: "lint", kind: "lint", hard: true, description: "Lint/typecheck no worse than before", verifier: "linter delta (skipped when none is configured)" },
      { id: "size_metric", kind: "metric", hard: true, description: "Largest module under 120 lines (stated in the task)", verifier: "line count" },
    ],
    [{ id: "readability", kind: "readability_review", hard: false, description: "Module boundaries are sensible", verifier: "model review" }],
    units, 5, c.strict
  );
  tl.at(1500, "plan", plan);
  tl.lane(1600, "spec-1", "spec", null, null, [["read_file", "wordstats/core.py"], ["symbols", "wordstats"], ["write_file", "tests/test_characterization.py"], ["run", "unittest on original", true, "14 passed"]], { at: 3100, status: "done" }, "Generated 14 characterization tests; all pass on the original.", SUPER);
  const ch = art(arts, { kind: "log", label: "characterization + API surface", phase: "n/a", mime: "text/plain" }, () => Buffer.from(logText("characterization.log")));
  tl.at(3100, "artifact", arts.find((a) => a.meta.id === ch).meta);
  [["u1", "tokenize", 4900], ["u2", "counter", 5600], ["u3", "report", 5300]].forEach(([u, m, end], i) => {
    tl.at(3200, "unit", { id: u, status: "running", files: [] });
    tl.lane(3200, `w-${u}-a`, "worker", u, "a", [["read_file", "wordstats/core.py"], ["symbols", m], ["write_file", `wordstats/${m}.py`], ["apply_patch", "wordstats/core.py"], ["run", "unittest"]], { at: end, status: "done" }, `Moved ${m} code into wordstats/${m}.py.`);
    const d = unifiedDiff(`wordstats/${m}.py`, "", `"""${m}"""\n\n\ndef ${m}_placeholder():\n    pass\n`) + unifiedDiff("wordstats/core.py", `def ${m}_placeholder():\n    pass\n# ... ${i}\n`, `# ${m} moved to wordstats/${m}.py\n# ... ${i}\n`);
    tl.at(end + 50, "unit", { id: u, status: "passed", winner_variant: "a", files: [`wordstats/${m}.py`, "wordstats/core.py"], diff: d });
  });
  tl.at(5800, "merge", { status: "conflict", units: ["u1", "u2", "u3"], conflicts: ["wordstats/core.py"] });
  tl.lane(5850, "integrator", "integrator", null, null, [["read_file", "wordstats/core.py"], ["apply_patch", "wordstats/core.py"], ["run", "unittest"]], { at: 7000, status: "done" }, "Three units each removed a block from core.py; merged them by hand.", SUPER);
  tl.at(7050, "merge", { status: "resolved", units: ["u1", "u2", "u3"], conflicts: ["wordstats/core.py"] });
  tl.at(7100, "unit", { id: "u4", status: "running", files: [] });
  tl.lane(7100, "w-u4-a", "worker", "u4", "a", [["read_file", "wordstats/__init__.py"], ["write_file", "wordstats/__init__.py"], ["run", "api surface diff"]], { at: 8300, status: "done" }, "Re-exported all 7 public names.");
  const d4 = unifiedDiff("wordstats/__init__.py", "from .core import tokenize, count_words, top_words, report\n", "from .tokenize import tokenize\nfrom .counter import count_words, top_words\nfrom .report import report\n");
  tl.at(8350, "unit", { id: "u4", status: "passed", winner_variant: "a", files: ["wordstats/__init__.py"], diff: d4 });
  tl.at(8500, "merge", { status: "ok", units: ["u4"], conflicts: [] });
  ["u1", "u2", "u3", "u4"].forEach((u) => tl.at(8550, "unit", { id: u, status: "merged", files: [] }));
  const r = [
    R("build", "build", true, "skip", "Python project: no build step"),
    R("no_regression", "no_regression", true, "pass", "12 of 12 baseline tests still pass"),
    R("policy", "policy", true, "pass", "no existing tests edited"),
    R("security", "security", true, "pass", "no new findings"),
    R("secrets", "secrets", true, "pass", "none added"),
    R("characterization", "characterization_tests", true, "pass", "14 of 14 pass before and after", { artifacts: [ch] }),
    R("api_surface", "api_surface", true, "pass", "7 exported symbols, 0 removed, 0 signatures changed", { artifacts: [ch] }),
    R("lint", "lint", true, "skip", "No linter configured in this repo; nothing to compare"),
    R("size_metric", "metric", true, "pass", "largest module 74 lines (was 281)"),
    R("readability", "readability_review", false, "advisory", "Boundaries follow the old section comments.", { score: 0.8 }),
  ];
  tl.at(8800, "verify", { round: 1, results: r, hard_pass: true, summary: summarize(r) });
  tl.lane(9000, "reviewer", "reviewer", null, null, [["read_file", "combined diff"], ["write_file", "PR description"]], { at: 9700, status: "done" }, "Wrote the PR description.", SUPER);
  const branch = `patchloop/${slug(c.task)}-${Math.floor(Date.now() / 1000)}`;
  tail(tl, 9800, {
    outcome: "complete", taskType: "refactor",
    best: { id: 1, parent: null, depth: 0, passed: 12, total: 12, score: 1, idea: "Combined swarm result", diff: d4, files: { "wordstats/__init__.py": "", "wordstats/tokenize.py": "", "wordstats/counter.py": "", "wordstats/report.py": "" } },
    hard: r.filter((x) => x.hard && x.status === "pass").length, hardTotal: r.filter((x) => x.hard).length, advisory: [{ id: "readability", score: 0.8 }],
    spawned: new Set(tl.ev.filter((e) => e.type === "agent").map((e) => e.data.id)).size, peak: 3, usage: tl.tokens, pr: c.autoPr ? { repo: c.repo.fullName, branch, commits: 4 } : null, prNumber: c.prNumber,
  });
  return { events: tl.sorted(), plan, artifacts: arts, lastVerify: r, best: tl.ev.find((e) => e.type === "done")?.data.best };
}

// ---------- scenario: partial (docs / perf / deps / other) ----------
function partialScenario(c) {
  const tl = new TL();
  const arts = [];
  head(tl, c.repo, c.branch, 9, c.repo.language.toLowerCase(), "python -m unittest");
  const units = [{ id: "u1", title: "Write the guide", scope_files: ["docs/MIGRATION.md"], depends_on: [], variants: 2, role: "worker" }, { id: "u2", title: "Link it from the README", scope_files: ["README.md"], depends_on: ["u1"], variants: 1, role: "worker" }];
  const plan = planCommon(
    c.type, c.source,
    "Write the requested material. Only the mechanical parts can be proven; the quality of the prose cannot, so it stays advisory.",
    [{ id: "links", kind: "link_check", hard: true, description: "Every link in the new/changed docs resolves", verifier: "link checker" }],
    [{ id: "newcomer", kind: "rubric", hard: false, description: "Reads clearly to a newcomer (no executable verifier exists for this)", verifier: "model rubric" }],
    units, 3, c.strict
  );
  tl.at(1500, "plan", plan);
  tl.at(1700, "unit", { id: "u1", status: "running", files: [] });
  tl.lane(1700, "w-u1-a", "worker", "u1", "a", [["read_file", "README.md"], ["search", "TODO"], ["write_file", "docs/MIGRATION.md"], ["run", "link check"]], { at: 4300, status: "done" }, "Wrote docs/MIGRATION.md.");
  tl.lane(1700, "w-u1-b", "worker", "u1", "b", [["read_file", "README.md"], ["write_file", "docs/MIGRATION.md"]], { at: 4350, status: "cancelled" }, "Cancelled: variant a passed first.");
  const d1 = unifiedDiff("docs/MIGRATION.md", "", "# Migration guide\n\n1. Update the package.\n2. Run the tests.\n");
  tl.at(4400, "unit", { id: "u1", status: "passed", winner_variant: "a", files: ["docs/MIGRATION.md"], diff: d1 });
  tl.at(4500, "unit", { id: "u2", status: "running", files: [] });
  tl.lane(4500, "w-u2-a", "worker", "u2", "a", [["read_file", "README.md"], ["write_file", "README.md"]], { at: 5400, status: "done" }, "Linked the guide from the README.");
  const d2 = unifiedDiff("README.md", "# project\n", "# project\n\nSee the [migration guide](docs/MIGRATION.md).\n");
  tl.at(5450, "unit", { id: "u2", status: "passed", winner_variant: "a", files: ["README.md"], diff: d2 });
  tl.at(5600, "merge", { status: "ok", units: ["u1", "u2"], conflicts: [] });
  ["u1", "u2"].forEach((u) => tl.at(5650, "unit", { id: u, status: "merged", files: [] }));
  const lk = art(arts, { kind: "log", label: "link check", phase: "after", mime: "text/plain" }, () => Buffer.from(logText("links.log")));
  tl.at(5900, "artifact", arts.find((a) => a.meta.id === lk).meta);
  const r = [
    R("build", "build", true, "skip", "No build step in this repo"),
    R("no_regression", "no_regression", true, "pass", "12 of 12 baseline tests still pass"),
    R("policy", "policy", true, "pass", "only docs files changed"),
    R("security", "security", true, "pass", "no new findings"),
    R("secrets", "secrets", true, "pass", "none added"),
    R("links", "link_check", true, "pass", "9 links, 0 broken", { artifacts: [lk] }),
    R("newcomer", "rubric", false, "advisory", "Reads clearly, but this has no executable check.", { score: 0.72 }),
  ];
  tl.at(6100, "verify", { round: 1, results: r, hard_pass: true, summary: summarize(r) });
  tl.lane(6300, "reviewer", "reviewer", null, null, [["write_file", "PR description"]], { at: 6900, status: "done" }, "Wrote the PR description, including what was not verified.", SUPER);
  const branch = `patchloop/${slug(c.task)}-${Math.floor(Date.now() / 1000)}`;
  tail(tl, 7000, {
    outcome: "partial", taskType: c.type,
    best: { id: 1, parent: null, depth: 0, passed: 6, total: 6, score: 1, idea: "Combined swarm result", diff: d1 + d2, files: { "docs/MIGRATION.md": "", "README.md": "" } },
    hard: r.filter((x) => x.hard && x.status === "pass").length, hardTotal: r.filter((x) => x.hard).length, advisory: [{ id: "newcomer", score: 0.72 }],
    extraCriteria: { unverified: ["Reads clearly to a newcomer: no executable verifier exists, so this was judged by a model only (advisory)."] },
    spawned: new Set(tl.ev.filter((e) => e.type === "agent").map((e) => e.data.id)).size, peak: 2, usage: tl.tokens, pr: c.autoPr ? { repo: c.repo.fullName, branch, commits: 2 } : null, prNumber: c.prNumber,
  });
  return { events: tl.sorted(), plan, artifacts: arts, lastVerify: r, best: tl.ev.find((e) => e.type === "done")?.data.best };
}

// ---------- scenario: unsolvable (honest failure, no PR) ----------
function unsolvableScenario(c) {
  const tl = new TL();
  head(tl, c.repo, c.branch, 9, "python", "python -m unittest");
  const units = [{ id: "u1", title: "Attempt the change", scope_files: ["shop/cart.py"], depends_on: [], variants: 2, role: "worker" }];
  const plan = planCommon(
    c.type, c.source, "The task asks for something the checks cannot accept (it would require editing existing tests). Trying within the rules.",
    [{ id: "acceptance", kind: "acceptance_tests", hard: true, description: "Acceptance tests written from the task pass", verifier: "unittest, before and after" }],
    [], units, 3, c.strict
  );
  tl.at(1500, "plan", plan);
  tl.at(1700, "unit", { id: "u1", status: "running", files: [] });
  tl.lane(1700, "w-u1-a", "worker", "u1", "a", [["read_file", "shop/cart.py"], ["write_file", "tests/test_cart.py", false, "blocked: existing tests are off limits"], ["write_file", "shop/cart.py"], ["run", "python -m unittest", false, "2 failed"]], { at: 4200, status: "failed" }, "Could not satisfy the acceptance tests within policy.");
  tl.lane(1700, "w-u1-b", "worker", "u1", "b", [["read_file", "shop/cart.py"], ["write_file", "shop/cart.py"], ["run", "python -m unittest", false, "3 failed"]], { at: 4500, status: "failed" }, "Acceptance tests still failing.");
  tl.at(4550, "unit", { id: "u1", status: "failed", files: [] });
  const r1 = [
    R("build", "build", true, "skip", "Python project: no build step"),
    R("no_regression", "no_regression", true, "pass", "13 of 13 baseline tests still pass"),
    R("policy", "policy", true, "pass", "no edits to existing tests"),
    R("security", "security", true, "pass", "no new findings"),
    R("secrets", "secrets", true, "pass", "none added"),
    R("acceptance", "acceptance_tests", true, "fail", "2 of 4 acceptance tests fail"),
  ];
  tl.at(4800, "verify", { round: 1, results: r1, hard_pass: false, summary: summarize(r1) });
  tl.lane(5000, "critic-1", "critic", null, null, [["read_file", "verify output"]], { at: 5600, status: "done" }, "Two tests contradict an existing test. Repair attempt limited by policy.", SUPER);
  tl.at(5700, "unit", { id: "u2", status: "running", files: [] });
  tl.lane(5700, "w-u2-a", "worker", "u2", "a", [["read_file", "shop/cart.py"], ["write_file", "shop/cart.py"], ["run", "python -m unittest", false, "2 failed"]], { at: 7500, status: "failed" }, "Repair did not fix the remaining failures.");
  tl.at(7550, "unit", { id: "u2", status: "failed", files: [] });
  tl.at(7800, "verify", { round: 2, results: r1, hard_pass: false, summary: summarize(r1) });
  tl.at(8000, "error", { stage: "verify", message: "Hard gates still failing after 2 rounds (round limit reached). Nothing was opened for merge." });
  tl.at(8100, "done", {
    solved: false, outcome: "failed", task_type: c.type,
    best: null, criteria: { hard_pass: 5, hard_total: 6, advisory: [] },
    usage: { prompt_tokens: Math.round(tl.tokens * 0.8), completion_tokens: Math.round(tl.tokens * 0.2) },
    latency_ms: 8100, time_to_first_event_ms: 180, agents: { spawned: 6, peak_parallel: 2 },
  });
  tl.at(8150, "end", {});
  return { events: tl.sorted(), plan, artifacts: [], lastVerify: r1, best: null };
}

// ---------- scenario: needs_input ----------
function needsInputScenario(c) {
  const tl = new TL();
  head(tl, c.repo, c.branch, 9, c.repo.language.toLowerCase(), "npm test");
  // head() already runs the planner to t=1500; replace its tail: planner asks instead of planning.
  tl.at(1600, "clarify", {
    questions: [
      { id: "q1", text: "Which part of the app should change, and what is wrong with it today?" },
      { id: "q2", text: "How will you know it is better: how it looks, how fast it is, or new behavior?" },
    ],
  });
  tl.at(1750, "done", { solved: false, outcome: "needs_input", task_type: "other", best: null, criteria: { hard_pass: 0, hard_total: 0, advisory: [] }, usage: { prompt_tokens: 900, completion_tokens: 200 }, latency_ms: 1750, time_to_first_event_ms: 160, agents: { spawned: 2, peak_parallel: 1 } });
  tl.at(1800, "end", {});
  return { events: tl.sorted(false), plan: null, artifacts: [], lastVerify: null, best: null };
}

// ---------- scenario: follow-up on an existing PR ----------
function followupScenario(c) {
  const tl = new TL();
  tl.at(0, "run_started", { run_id: null, bug_id: "", mode: "fake", engine: "swarm" });
  tl.at(120, "repo", { full_name: c.repo.fullName, branch: c.branch, files: 9, language: c.repo.language.toLowerCase(), test_command: "npm test", truncated: false });
  const plan = planCommon(c.type, "auto", `Follow-up on the existing pull request: ${c.followup.slice(0, 120)}`, [], [], [{ id: "u1", title: "Apply the requested change", scope_files: [], depends_on: [], variants: 1, role: "worker" }], 1, []);
  tl.at(600, "plan", plan);
  tl.at(700, "unit", { id: "u1", status: "running", files: [] });
  tl.lane(700, "w-u1-a", "worker", "u1", "a", [["read_file", "src/App.jsx"], ["write_file", "src/App.jsx"], ["run", "npm run build"]], { at: 2400, status: "done" }, "Applied the requested change on top of the earlier patch.");
  tl.at(2450, "unit", { id: "u1", status: "passed", winner_variant: "a", files: ["src/App.jsx"], diff: unifiedDiff("src/App.jsx", "a\n", "b\n") });
  tl.at(2600, "merge", { status: "ok", units: ["u1"], conflicts: [] });
  const r = [R("build", "build", true, "pass", "build ok"), R("no_regression", "no_regression", true, "pass", "all baseline tests pass"), R("policy", "policy", true, "pass", "ok"), R("security", "security", true, "pass", "ok"), R("secrets", "secrets", true, "pass", "ok")];
  tl.at(2900, "verify", { round: 1, results: r, hard_pass: true, summary: summarize(r) });
  tail(tl, 3100, { outcome: "complete", taskType: c.type, best: { id: 1, parent: null, depth: 0, passed: 5, total: 5, score: 1, diff: unifiedDiff("src/App.jsx", "a\n", "b\n"), files: { "src/App.jsx": "" } }, hard: 5, hardTotal: 5, advisory: [], spawned: 3, peak: 1, usage: tl.tokens, pr: null });
  // the follow-up updates the same PR
  const done = tl.ev.find((e) => e.type === "pr");
  if (!done) tl.at(3800, "pr", { url: c.prUrl, branch: c.prBranch, number: c.prNumber, fake: true, updated: true, commits: 1 });
  const end = tl.ev.find((e) => e.type === "end");
  end.at = 3850;
  return { events: tl.sorted(), plan, artifacts: [], lastVerify: r, best: tl.ev.find((e) => e.type === "done")?.data.best };
}

export function buildSwarm(kind, ctx) {
  switch (kind) {
    case "ui": return uiScenario(ctx);
    case "feature": return featureScenario(ctx);
    case "refactor": return refactorScenario(ctx);
    case "unsolvable": return unsolvableScenario(ctx);
    case "needs_input": return needsInputScenario(ctx);
    case "followup": return followupScenario(ctx);
    default: return partialScenario(ctx);
  }
}
