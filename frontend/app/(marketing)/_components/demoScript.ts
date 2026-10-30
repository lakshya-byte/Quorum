import type { StreamMessage } from "../../_lib/runState";

// A scripted replay of a swarm run, fed through the same reducer the live run page uses.
// Scenario: "Improve the UI of this React app" on a small demo todo app. Everything here is invented
// for the landing page (timings, agents, check details); a real run streams the same event types.

const NANO = "nemotron-nano";
const SUPER = "nemotron-super";
type Ev = { at: number; msg: StreamMessage };
const ev: Ev[] = [];
const at = (t: number, type: string, data: Record<string, unknown>) => ev.push({ at: t, msg: { type, data } });
const agent = (t: number, id: string, role: string, status: string, x: Record<string, unknown> = {}) => at(t, "agent", { id, role, unit_id: null, variant: null, model: SUPER, isolation: "local", status, ...x });
const tool = (t: number, agent_id: string, name: string, target: string, ok = true, note?: string) => at(t, "tool", { agent_id, name, target, ok, ms: 120, ...(note ? { note } : {}) });

const C = (id: string, kind: string, hard: boolean, description: string) => ({ id, kind, hard, description });
const criteria = [
  C("build", "build", true, "Install and build succeed in the sandbox"),
  C("no_regression", "no_regression", true, "Every test that passed on the original still passes"),
  C("policy", "policy", true, "No .github/ edits, no edits to existing tests"),
  C("security", "security", true, "No new high-severity findings"),
  C("secrets", "secrets", true, "No secret-looking strings added"),
  C("ui_console", "console_errors", true, "No console errors on load"),
  C("ui_overflow", "no_overflow", true, "No horizontal overflow at 375, 768, 1280 px"),
  C("ui_axe", "a11y_axe", true, "axe-core violations do not increase"),
  C("ui_smoke", "smoke", true, "Add, complete, delete a todo: passes before and after"),
  C("ui_vision", "vision_rubric", false, "Hierarchy, spacing, contrast (vision rubric, advisory)"),
  C("readability", "readability_review", false, "Diff reads well (model review, advisory)"),
];
const R = (criterion_id: string, hard: boolean, status: string, detail: string, score?: number) => ({ criterion_id, kind: criterion_id, hard, status, detail, ...(score != null ? { score } : {}), artifacts: [] });
const ok = [
  R("build", true, "pass", "vite build ok"),
  R("no_regression", true, "pass", "13 of 13 baseline tests pass"),
  R("policy", true, "pass", "no .github/ or test edits"),
  R("security", true, "pass", "no new findings"),
  R("secrets", true, "pass", "none added"),
  R("ui_console", true, "pass", "0 console errors"),
  R("ui_overflow", true, "pass", "no overflow at 375, 768, 1280"),
  R("ui_axe", true, "pass", "violations 5 to 1"),
  R("ui_smoke", true, "pass", "pass before and after"),
  R("ui_vision", false, "advisory", "clearer hierarchy", 0.83),
  R("readability", false, "advisory", "small, focused diff", 0.81),
];
const r1 = ok.map((r) => (r.criterion_id === "ui_overflow" ? R("ui_overflow", true, "fail", "375px: scrollWidth 612 > 375") : r));
const sum = (rs: typeof ok) => ({ pass: rs.filter((r) => r.status === "pass").length, fail: rs.filter((r) => r.status === "fail").length, skip: 0, advisory: rs.filter((r) => r.status === "advisory").length });

at(200, "run_started", { mode: "fake", engine: "swarm" });
at(500, "repo", { full_name: "demo/react-todo", branch: "main", files: 11, language: "javascript", test_command: "npm test" });
agent(700, "planner", "planner", "running");
tool(1000, "planner", "list_dir", ".");
tool(1300, "planner", "symbols", "entrypoints");
at(1700, "plan", {
  task_type: "ui",
  task_type_source: "auto",
  summary: "Improve the look and responsiveness of the todo app without changing behavior.",
  criteria,
  units: [
    { id: "u1", title: "Design tokens and base styles", scope_files: ["src/App.css"], depends_on: [], variants: 2 },
    { id: "u2", title: "Restyle list and form", scope_files: ["src/components/TodoList.jsx"], depends_on: ["u1"], variants: 2 },
  ],
  swarm: { max_parallel: 4, workers_planned: 4, limits: { max_workers: 8 } },
});
agent(1750, "planner", "planner", "done", { summary: "Planned 2 units." });
agent(1900, "spec-1", "spec", "running");
tool(2200, "spec-1", "write_file", "tests/ui/smoke.spec.js");
agent(2700, "spec-1", "spec", "done", { summary: "UI checks written and run on the original." });
at(2750, "artifact", { id: "b375", kind: "screenshot", label: "Todo page", phase: "before", viewport: 375, mime: "image/png" });
agent(2900, "w-u1-a", "worker", "running", { unit_id: "u1", variant: "a", model: NANO });
agent(2900, "w-u1-b", "worker", "running", { unit_id: "u1", variant: "b", model: NANO });
at(2900, "unit", { id: "u1", status: "running", files: [] });
tool(3300, "w-u1-a", "write_file", "src/App.css");
tool(3400, "w-u1-b", "write_file", "src/App.css");
tool(3900, "w-u1-a", "run", "npm run build");
agent(4400, "w-u1-a", "worker", "done", { unit_id: "u1", variant: "a", model: NANO, summary: "Tokens, system font, spacing scale.", steps: 5 });
agent(4450, "w-u1-b", "worker", "cancelled", { unit_id: "u1", variant: "b", model: NANO, summary: "Cancelled: variant a passed first." });
at(4500, "unit", { id: "u1", status: "passed", winner_variant: "a", files: ["src/App.css"] });
agent(4700, "w-u2-a", "worker", "running", { unit_id: "u2", variant: "a", model: NANO });
agent(4700, "w-u2-b", "worker", "running", { unit_id: "u2", variant: "b", model: NANO });
at(4700, "unit", { id: "u2", status: "running", files: [] });
tool(5100, "w-u2-a", "write_file", "src/components/TodoList.jsx");
tool(5200, "w-u2-b", "write_file", "src/components/TodoList.jsx");
tool(5600, "w-u2-a", "run", "axe unit check", false, "contrast 2.9:1");
agent(5900, "w-u2-a", "worker", "failed", { unit_id: "u2", variant: "a", model: NANO, summary: "Failed the unit's axe check." });
agent(6300, "w-u2-b", "worker", "done", { unit_id: "u2", variant: "b", model: NANO, summary: "Card list, labelled input, focus styles.", steps: 6 });
at(6350, "unit", { id: "u2", status: "passed", winner_variant: "b", files: ["src/components/TodoList.jsx"] });
at(6600, "merge", { status: "ok", units: ["u1", "u2"], conflicts: [] });
at(7000, "verify", { round: 1, results: r1, hard_pass: false, summary: sum(r1) });
agent(7300, "critic-1", "critic", "running");
agent(7900, "critic-1", "critic", "done", { summary: "Overflow at 375px: one table left. Repair unit u3." });
agent(8000, "w-u3-a", "worker", "running", { unit_id: "u3", variant: "a", model: NANO });
at(8000, "unit", { id: "u3", status: "running", files: [] });
tool(8500, "w-u3-a", "run", "overflow check 375");
agent(9300, "w-u3-a", "worker", "done", { unit_id: "u3", variant: "a", model: NANO, summary: "Replaced the last table with a list.", steps: 5 });
at(9350, "unit", { id: "u3", status: "passed", winner_variant: "a", files: ["src/App.css"] });
at(9500, "merge", { status: "ok", units: ["u3"], conflicts: [] });
at(9700, "artifact", { id: "a375", kind: "screenshot", label: "Todo page", phase: "after", viewport: 375, mime: "image/png" });
at(10200, "verify", { round: 2, results: ok, hard_pass: true, summary: sum(ok) });
agent(10400, "reviewer", "reviewer", "running");
agent(10900, "reviewer", "reviewer", "done", { summary: "PR text written with the evidence table." });
at(11100, "done", {
  solved: true,
  outcome: "complete",
  task_type: "ui",
  best: null,
  criteria: { hard_pass: 9, hard_total: 9, advisory: [] },
  usage: { prompt_tokens: 18200, completion_tokens: 4300 },
  latency_ms: 11100,
  agents: { spawned: 9, peak_parallel: 3 },
});
at(11500, "pr", { url: "https://github.com/demo/react-todo/pull/7", branch: "patchloop/improve-the-ui", number: 7, fake: true, commits: 3 });
at(11550, "end", {});

export const DEMO_EVENTS: Ev[] = ev;
export const DEMO_TOTAL_MS = 11600;
