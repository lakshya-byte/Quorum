// Swarm (contract v3) state: plan, agents, units, merges, verification rounds, artifacts, budget.
// Pure data + helpers; the reducer in runState.ts folds events into SwarmState.

import type { ArtifactMeta, CriteriaSummary, CriterionStatus, Outcome, Plan, PlanCriterion, TaskType, VerifyResultRow } from "./api";

export type AgentStatus = "spawned" | "running" | "done" | "failed" | "cancelled";
export type ToolEvent = { agent_id: string; name: string; target?: string; ok: boolean; ms?: number; note?: string };
export type AgentState = {
  id: string;
  role: string;
  unit_id: string | null;
  variant: string | null;
  status: AgentStatus;
  model?: string | null;
  isolation?: "nebius" | "local" | string;
  summary?: string;
  tokens?: number;
  steps?: number;
  tools: ToolEvent[]; // most recent first, capped
  toolCount: number;
  order: number;
};
export type UnitStatus = "pending" | "running" | "passed" | "failed" | "cancelled" | "merged";
export type UnitState = { id: string; status: UnitStatus; winner_variant?: string | null; files: string[]; diff?: string; checks?: unknown };
export type MergeState = { status: "ok" | "conflict" | "resolved" | "failed"; units: string[]; conflicts: string[] };
export type VerifyRound = {
  round: number;
  results: VerifyResultRow[];
  hard_pass: boolean;
  summary: { pass: number; fail: number; skip: number; advisory: number };
};
export type BudgetState = { tokens_used: number; tokens_limit: number; wall_s: number; wall_limit_s: number; workers_active: number };
export type ClarifyQuestion = { id: string; text: string };

export type SwarmState = {
  plan: Plan | null;
  clarify: ClarifyQuestion[] | null;
  agents: Record<string, AgentState>;
  agentOrder: string[];
  units: Record<string, UnitState>;
  merges: MergeState[];
  verifies: VerifyRound[];
  artifacts: ArtifactMeta[];
  budget: BudgetState | null;
  peakParallel: number;
  /** from a saved run: counts only, no per-agent timeline */
  saved: { agentsSpawned?: number | null; peakParallel?: number | null; criteriaSummary?: CriteriaSummary | null } | null;
};

export const initialSwarm: SwarmState = {
  plan: null,
  clarify: null,
  agents: {},
  agentOrder: [],
  units: {},
  merges: [],
  verifies: [],
  artifacts: [],
  budget: null,
  peakParallel: 0,
  saved: null,
};

export const TOOL_KEEP = 12;

export const TYPE_LABEL: Record<string, string> = {
  auto: "Auto",
  bugfix: "Bug fix",
  feature: "Feature",
  refactor: "Refactor",
  ui: "UI/UX",
  tests: "Tests",
  perf: "Performance",
  deps: "Dependencies",
  docs: "Docs",
  migration: "Migration",
  other: "Other",
};
export const typeLabel = (t?: string | null) => (t ? TYPE_LABEL[t] || t : "Task");

export const OUTCOME_LABEL: Record<Outcome, string> = { complete: "Complete", partial: "Partial", failed: "Failed", needs_input: "Needs input", blocked: "Blocked" };

export function isSwarmState(s: { swarm: SwarmState }): boolean {
  const w = s.swarm;
  if (w.clarify) return true;
  if (w.agentOrder.length > 0 || w.verifies.length > 0) return true;
  return !!w.plan && w.plan.task_type !== "bugfix";
}

export function activeAgents(w: SwarmState): AgentState[] {
  return w.agentOrder.map((id) => w.agents[id]).filter((a) => a && (a.status === "running" || a.status === "spawned"));
}

export type HardCount = { pass: number; total: number };
/** Hard-gate counts from the latest verify round, else from a saved criteria summary. */
export function hardCount(w: SwarmState): HardCount | null {
  const last = w.verifies[w.verifies.length - 1];
  if (last) {
    const hard = last.results.filter((r) => r.hard);
    // a skipped hard gate proved nothing, so it does not count as passed
    return { pass: hard.filter((r) => r.status === "pass").length, total: hard.length };
  }
  return savedHardCount(w.saved?.criteriaSummary);
}

export function savedHardCount(c?: CriteriaSummary | null): HardCount | null {
  if (!c) return null;
  const total = c.hard_total ?? c.hardTotal;
  const pass = c.hard_pass ?? c.hardPass;
  if (typeof total === "number" && typeof pass === "number") return { pass, total };
  if (typeof total === "number" && typeof pass === "boolean") return { pass: pass ? total : 0, total };
  if (c.results) {
    const hard = c.results.filter((r) => r.hard);
    return { pass: hard.filter((r) => r.status === "pass").length, total: hard.length };
  }
  return null;
}

/** Rows for the gate table: latest results if any, else plan criteria with no status yet. */
export function gateRows(w: SwarmState): { criterion: PlanCriterion; result: VerifyResultRow | null }[] {
  const plan = w.plan?.criteria || [];
  const last = w.verifies[w.verifies.length - 1];
  const results = last?.results || w.saved?.criteriaSummary?.results || [];
  const byId = new Map(results.map((r) => [r.criterion_id, r]));
  const rows = plan.map((c) => ({ criterion: c, result: byId.get(c.id) ?? null }));
  for (const r of results) {
    if (!plan.some((c) => c.id === r.criterion_id)) {
      rows.push({ criterion: { id: r.criterion_id, kind: r.kind, hard: r.hard, description: r.criterion_id }, result: r });
    }
  }
  return rows;
}

export function statusOrder(s: CriterionStatus | undefined): number {
  return s === "fail" ? 0 : s === "advisory" ? 2 : s === "skip" ? 3 : s === "pass" ? 4 : 1;
}

/** Which pipeline vocabulary to use for a task type. */
export function stageWords(t?: string | null): { spec: string; work: string } {
  switch (t as TaskType) {
    case "feature":
      return { spec: "Acceptance tests", work: "Implement" };
    case "refactor":
      return { spec: "Characterize", work: "Refactor" };
    case "ui":
      return { spec: "UI checks", work: "Restyle" };
    case "bugfix":
      return { spec: "Reproduce", work: "Fix" };
    case "tests":
      return { spec: "Targets", work: "Write tests" };
    case "perf":
      return { spec: "Benchmark", work: "Optimize" };
    case "deps":
      return { spec: "Audit", work: "Upgrade" };
    case "docs":
      return { spec: "Checks", work: "Write" };
    default:
      return { spec: "Verifiers", work: "Work" };
  }
}

export function fmtTokens(n: number): string {
  if (n >= 10000) return `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k`;
  return n.toLocaleString();
}
export function fmtSecs(s: number): string {
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}
