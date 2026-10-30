// Pure reducer that folds the run event stream into renderable state.
// It is idempotent: a reconnect replays earlier events and nothing doubles up.
// Node objects keep their identity once stored, so memoised cards only
// re-render when their own data changes.

import type { ArtifactMeta, Outcome, Plan, Run, RunNode, Usage, VerifyResultRow, CriteriaSummary } from "./api";
import { TOOL_KEEP, initialSwarm, type AgentState, type SwarmState, type ToolEvent, type UnitState } from "./swarm";

export type GuardStage = "input" | "policy" | "output";
export type GuardEvent = {
  stage: GuardStage;
  verdict: "pass" | "block";
  reasons?: string[];
  latency_ms?: number;
  /** true when summarised from node.policy (the agent sends policy per node, not as a guard event) */
  derived?: boolean;
};
export type DoneEvent = {
  solved: boolean;
  best: number | null;
  usage?: Usage;
  latency_ms?: number;
  time_to_first_node_ms?: number | null;
  /** v3 */
  outcome?: Outcome;
  task_type?: string;
  criteria?: { hard_pass?: number | boolean; hard_total?: number; advisory?: unknown[] };
  agents?: { spawned?: number; peak_parallel?: number };
};

export type RepoEvent = { full_name: string; branch: string; files?: number; language?: string; test_command?: string; truncated?: boolean };
export type LocateEvent = { files: { path: string; reason?: string }[] };
export type ReproEvent = { path?: string; test_name?: string; failed_on_original: boolean; output_tail?: string };
export type PrEvent = { url: string; branch?: string; number?: number; fake?: boolean; updated?: boolean; commits?: number };

export type StreamStatus = "idle" | "connecting" | "live" | "reconnecting" | "finished" | "lost";

export type RunState = {
  status: StreamStatus;
  runId: string | null;
  bugId: string | null;
  mode: string | null;
  engine: string | null;
  guards: Partial<Record<GuardStage, GuardEvent>>;
  triage: { cause: string; strategies: string[] } | null;
  nodes: Record<number, RunNode>;
  order: number[]; // arrival order
  children: Record<number, number[]>; // parent id -> child ids (root key -1)
  lessons: Record<number, string[]>;
  depth: number;
  done: DoneEvent | null;
  prUrl: string | null;
  repo: RepoEvent | null;
  locate: LocateEvent | null;
  repro: ReproEvent | null;
  pr: PrEvent | null;
  errors: { stage?: string; message: string }[];
  blocked: boolean;
  tokens: number;
  startedAt: number | null; // client clock
  firstNodeAt: number | null;
  endedAt: number | null;
  fromSnapshot: boolean;
  attempt: number;
  swarm: SwarmState;
};

export const initialRunState: RunState = {
  status: "idle",
  runId: null,
  bugId: null,
  mode: null,
  engine: null,
  guards: {},
  triage: null,
  nodes: {},
  order: [],
  children: {},
  lessons: {},
  depth: 0,
  done: null,
  prUrl: null,
  repo: null,
  locate: null,
  repro: null,
  pr: null,
  errors: [],
  blocked: false,
  tokens: 0,
  startedAt: null,
  firstNodeAt: null,
  endedAt: null,
  fromSnapshot: false,
  attempt: 0,
  swarm: initialSwarm,
};

export type StreamMessage = { type: string; data?: Record<string, unknown> };

export type RunAction =
  | { kind: "connecting"; at: number }
  | { kind: "reconnecting"; attempt: number }
  | { kind: "lost" }
  | { kind: "event"; msg: StreamMessage; at: number }
  | { kind: "snapshot"; run: Run }
  | { kind: "pr"; url: string }
  | { kind: "reset" };

export function nodeTokens(n: RunNode): number {
  const t = n.tokens;
  if (typeof t === "number") return t;
  if (t && typeof t === "object") return (t.prompt_tokens || 0) + (t.completion_tokens || 0);
  return 0;
}

function addNode(s: RunState, n: RunNode): RunState {
  if (typeof n?.id !== "number") return s;
  const existing = s.nodes[n.id];
  const nodes = { ...s.nodes, [n.id]: n };
  let { order, children, tokens } = s;
  if (!existing) {
    order = [...order, n.id];
    const key = n.parent == null ? -1 : n.parent;
    children = { ...children, [key]: [...(children[key] || []), n.id] };
    tokens += nodeTokens(n);
  }
  let guards = s.guards;
  // CONTRACT: the policy gate result travels on each node (node.policy), not as a guard event.
  // Summarise it for the policy pill; a blocked candidate never blocks the whole run.
  if (n.policy && (!guards.policy || guards.policy.derived)) {
    const blockedIds = Object.values(nodes)
      .filter((x) => x.policy && x.policy.ok === false)
      .map((x) => `#${x.id}`);
    guards = {
      ...guards,
      policy: {
        stage: "policy",
        verdict: "pass",
        derived: true,
        reasons: blockedIds.length ? [`blocked before execution: ${blockedIds.join(", ")}`] : ["every candidate passed the gate"],
      },
    };
  }
  return { ...s, nodes, order, children, tokens, guards, depth: Math.max(s.depth, n.depth || 0) };
}

/** done.best is the best node object in the agent's stream (a node id in saved runs and mocks). */
export function bestNodeId(best: unknown): number | null {
  if (typeof best === "number") return best;
  if (best && typeof best === "object" && typeof (best as { id?: unknown }).id === "number") return (best as { id: number }).id;
  return null;
}

export function runReducer(s: RunState, a: RunAction): RunState {
  switch (a.kind) {
    case "reset":
      return initialRunState;
    case "connecting":
      return { ...s, status: s.status === "finished" ? s.status : "connecting", startedAt: s.startedAt ?? a.at };
    case "reconnecting":
      return s.status === "finished" ? s : { ...s, status: "reconnecting", attempt: a.attempt };
    case "lost":
      return s.status === "finished" ? s : { ...s, status: "lost" };
    case "pr":
      return { ...s, prUrl: a.url, pr: s.pr ?? { url: a.url } };
    case "snapshot": {
      const r = a.run;
      const finished = isFinishedRun(r);
      let next: RunState = {
        ...initialRunState,
        status: finished ? "finished" : "connecting",
        runId: r.id,
        bugId: r.bugId,
        mode: r.mode,
        engine: r.engine,
        prUrl: r.prUrl || null,
        pr: r.prUrl ? { url: r.prUrl, branch: r.branch, number: r.prNumber ?? undefined } : null,
        repo: r.kind === "repo" && r.repo ? { full_name: r.repo, branch: r.branch || "" } : null,
        fromSnapshot: true,
      };
      for (const n of r.nodes || []) next = addNode(next, n);
      if (r.plan || r.outcome || r.artifacts?.length || r.criteriaSummary) {
        next = {
          ...next,
          swarm: {
            ...initialSwarm,
            plan: r.plan || null,
            artifacts: r.artifacts || [],
            saved: { agentsSpawned: r.agentsSpawned, peakParallel: r.peakParallel, criteriaSummary: r.criteriaSummary },
          },
        };
      }
      if (finished) {
        next.done = {
          solved: r.solved,
          best: r.bestNodeId,
          usage: r.usage || undefined,
          latency_ms: r.latencyMs ?? undefined,
          ...(r.outcome ? { outcome: r.outcome } : {}),
          ...(r.taskType ? { task_type: r.taskType } : {}),
          ...(r.agentsSpawned != null ? { agents: { spawned: r.agentsSpawned, peak_parallel: r.peakParallel ?? undefined } } : {}),
        };
        if (r.outcome === "needs_input") next.errors = [];
        if (r.status === "failed" && !r.solved) next.errors = [{ message: "This run failed before it finished." }];
      }
      return next;
    }
    case "event": {
      const { type } = a.msg;
      const d = (a.msg.data || {}) as Record<string, unknown>;
      const base: RunState = s.status === "connecting" || s.status === "reconnecting" ? { ...s, status: "live", attempt: 0 } : s;
      switch (type) {
        case "run_started":
          return {
            ...base,
            runId: (d.run_id as string) ?? base.runId,
            bugId: (d.bug_id as string) ?? base.bugId,
            mode: (d.mode as string) ?? base.mode,
            engine: (d.engine as string) ?? base.engine,
          };
        case "guard": {
          const g = d as unknown as GuardEvent;
          if (!g.stage) return base;
          return {
            ...base,
            guards: { ...base.guards, [g.stage]: g },
            blocked: base.blocked || g.verdict === "block",
          };
        }
        case "triage":
          return {
            ...base,
            triage: { cause: String(d.cause || ""), strategies: Array.isArray(d.strategies) ? (d.strategies as string[]) : [] },
          };
        case "round":
          return { ...base, depth: Math.max(base.depth, Number(d.depth) || 0) };
        case "node": {
          const next = addNode(base, d as unknown as RunNode);
          return next.firstNodeAt == null ? { ...next, firstNodeAt: a.at } : next;
        }
        case "critic": {
          const id = Number(d.node_id);
          const lesson = String(d.lesson || "");
          if (!lesson || Number.isNaN(id)) return base;
          const prev = base.lessons[id] || [];
          if (prev.includes(lesson)) return base;
          return { ...base, lessons: { ...base.lessons, [id]: [...prev, lesson] } };
        }
        case "done":
          return { ...base, done: { ...(d as unknown as DoneEvent), best: bestNodeId(d.best) }, endedAt: base.endedAt ?? a.at };
        case "repo":
          return { ...base, repo: d as unknown as RepoEvent };
        case "locate":
          return { ...base, locate: { files: Array.isArray(d.files) ? (d.files as LocateEvent["files"]) : [] } };
        case "repro":
          return { ...base, repro: d as unknown as ReproEvent };
        case "pr":
          return d.url ? { ...base, prUrl: String(d.url), pr: d as unknown as PrEvent } : base;
        case "error": {
          const e = { stage: d.stage as string | undefined, message: String(d.message || "The run failed.") };
          if (base.errors.some((x) => x.message === e.message && x.stage === e.stage)) return base;
          return { ...base, errors: [...base.errors, e] };
        }
        case "plan":
          return { ...base, swarm: { ...base.swarm, plan: d as unknown as Plan } };
        case "clarify": {
          const q = Array.isArray(d.questions) ? (d.questions as { id: string; text: string }[]) : [];
          return { ...base, swarm: { ...base.swarm, clarify: q } };
        }
        case "agent":
          return swarmAgent(base, d);
        case "tool":
          return swarmTool(base, d);
        case "unit": {
          const id = String(d.id || "");
          if (!id) return base;
          const prev = base.swarm.units[id];
          const u: UnitState = {
            id,
            status: (d.status as UnitState["status"]) || prev?.status || "pending",
            winner_variant: (d.winner_variant as string | undefined) ?? prev?.winner_variant,
            files: Array.isArray(d.files) ? (d.files as string[]) : prev?.files || [],
            diff: (d.diff as string | undefined) ?? prev?.diff,
            checks: d.checks ?? prev?.checks,
          };
          return { ...base, swarm: { ...base.swarm, units: { ...base.swarm.units, [id]: u } } };
        }
        case "merge": {
          const m = { status: d.status as "ok", units: (d.units as string[]) || [], conflicts: (d.conflicts as string[]) || [] };
          return { ...base, swarm: { ...base.swarm, merges: [...base.swarm.merges, m] } };
        }
        case "verify": {
          const round = Number(d.round) || base.swarm.verifies.length + 1;
          const v = {
            round,
            results: (d.results as VerifyResultRow[]) || [],
            hard_pass: !!d.hard_pass,
            summary: (d.summary as { pass: number; fail: number; skip: number; advisory: number }) || { pass: 0, fail: 0, skip: 0, advisory: 0 },
          };
          const rest = base.swarm.verifies.filter((x) => x.round !== round);
          return { ...base, swarm: { ...base.swarm, verifies: [...rest, v].sort((a, b) => a.round - b.round) } };
        }
        case "artifact": {
          const a = d as unknown as ArtifactMeta;
          if (!a.id || base.swarm.artifacts.some((x) => x.id === a.id)) return base;
          return { ...base, swarm: { ...base.swarm, artifacts: [...base.swarm.artifacts, a] } };
        }
        case "budget":
          return { ...base, swarm: { ...base.swarm, budget: d as unknown as SwarmState["budget"] } };
        case "end":
          return { ...base, status: "finished", endedAt: base.endedAt ?? a.at };
        default:
          return base; // unknown event types are ignored on purpose
      }
    }
  }
}

function swarmAgent(s: RunState, d: Record<string, unknown>): RunState {
  const id = String(d.id || "");
  if (!id) return s;
  const w = s.swarm;
  const prev = w.agents[id];
  const a: AgentState = {
    id,
    role: String(d.role || prev?.role || "worker"),
    unit_id: (d.unit_id as string | null | undefined) ?? prev?.unit_id ?? null,
    variant: (d.variant as string | null | undefined) ?? prev?.variant ?? null,
    status: (d.status as AgentState["status"]) || prev?.status || "spawned",
    model: (d.model as string | null | undefined) ?? prev?.model,
    isolation: (d.isolation as string | undefined) ?? prev?.isolation,
    summary: (d.summary as string | undefined) ?? prev?.summary,
    tokens: (d.tokens as number | undefined) ?? prev?.tokens,
    steps: (d.steps as number | undefined) ?? prev?.steps,
    tools: prev?.tools || [],
    toolCount: prev?.toolCount || 0,
    order: prev?.order ?? w.agentOrder.length,
  };
  const agents = { ...w.agents, [id]: a };
  const agentOrder = prev ? w.agentOrder : [...w.agentOrder, id];
  const running = agentOrder.filter((x) => agents[x].status === "running" || agents[x].status === "spawned").length;
  return { ...s, swarm: { ...w, agents, agentOrder, peakParallel: Math.max(w.peakParallel, running) } };
}

function swarmTool(s: RunState, d: Record<string, unknown>): RunState {
  const t = d as unknown as ToolEvent;
  const prev = s.swarm.agents[t.agent_id];
  if (!prev) return s;
  const a: AgentState = { ...prev, tools: [t, ...prev.tools].slice(0, TOOL_KEEP), toolCount: prev.toolCount + 1 };
  return { ...s, swarm: { ...s.swarm, agents: { ...s.swarm.agents, [a.id]: a } } };
}

export type { CriteriaSummary };

export function isFinishedRun(r: Run): boolean {
  if (r.completedAt) return true;
  return !["running", "queued", "pending", "started", "created"].includes((r.status || "").toLowerCase());
}

export type NodeTone = "green" | "amber" | "red";

export function nodeTone(n: RunNode): NodeTone {
  if (n.policy && n.policy.ok === false) return "red";
  if (n.total > 0 && n.passed >= n.total) return "green";
  if (n.passed > 0) return "amber";
  return "red";
}

export function totalTokens(s: RunState): number {
  const u = s.done?.usage;
  if (u && (u.prompt_tokens || u.completion_tokens)) return (u.prompt_tokens || 0) + (u.completion_tokens || 0);
  return s.tokens;
}

// ---- pipeline view (repo runs) ----
export type StageId = "repo" | "locate" | "repro" | "propose" | "test" | "critic" | "review" | "pr";
export type StageState = "pending" | "active" | "done" | "skipped" | "warn";
export const STAGES: { id: StageId; label: string; hint: string }[] = [
  { id: "repo", label: "Repo", hint: "Read the repository" },
  { id: "locate", label: "Locate", hint: "Find the files that matter" },
  { id: "repro", label: "Repro", hint: "Write a test that fails today" },
  { id: "propose", label: "Propose", hint: "Parallel fix candidates" },
  { id: "test", label: "Test", hint: "Run each in a sandbox" },
  { id: "critic", label: "Critic", hint: "Learn from failures" },
  { id: "review", label: "Review", hint: "Reviewer and output guard" },
  { id: "pr", label: "PR", hint: "Open a pull request" },
];

export function isRepoRun(s: RunState): boolean {
  return !!(s.repo || s.locate || s.repro || s.pr);
}

export function pipelineStages(s: RunState): { id: StageId; label: string; hint: string; state: StageState; detail?: string }[] {
  const nonRoot = Object.values(s.nodes).filter((n) => n.parent != null);
  const finished = s.status === "finished" || !!s.done;
  const solved = !!s.done?.solved;
  const ev: Record<StageId, boolean> = {
    repo: !!s.repo,
    locate: !!s.locate,
    repro: !!s.repro,
    propose: nonRoot.length > 0,
    test: nonRoot.some((n) => n.total > 0),
    critic: Object.keys(s.lessons).length > 0,
    review: !!s.guards.output || solved,
    pr: !!s.pr,
  };
  let reached = -1;
  STAGES.forEach((st, i) => {
    if (ev[st.id]) reached = i;
  });
  if (finished) reached = solved ? STAGES.length - 1 : Math.max(reached, 4);
  const detail: Partial<Record<StageId, string>> = {
    repo: s.repo ? `${s.repo.files ?? "?"} files · ${s.repo.language || "unknown"}` : undefined,
    locate: s.locate ? `${s.locate.files.length} file${s.locate.files.length === 1 ? "" : "s"}` : undefined,
    repro: s.repro ? (s.repro.failed_on_original ? "fails on original" : "not reproduced") : undefined,
    propose: nonRoot.length ? `${nonRoot.length} candidate${nonRoot.length === 1 ? "" : "s"}` : undefined,
    pr: s.pr ? (s.pr.number ? `#${s.pr.number}` : "opened") : undefined,
  };
  return STAGES.map((st, i) => {
    let state: StageState;
    if (finished) {
      if (!solved && (st.id === "review" || st.id === "pr")) state = "skipped";
      else if (st.id === "pr" && !s.pr) state = "skipped";
      else if (st.id === "repro" && s.repro && !s.repro.failed_on_original) state = "warn";
      else if (!ev[st.id] && i < reached && !(st.id === "repo" || st.id === "locate")) state = "done";
      else state = ev[st.id] || i <= reached ? "done" : "skipped";
    } else if (i < reached) state = "done";
    else if (i === reached) state = "active";
    else if (i === reached + 1 && s.status !== "idle") state = "active";
    else state = "pending";
    if (!finished && i === reached && ev[st.id] && (st.id === "repo" || st.id === "locate" || st.id === "repro") ) state = "done";
    return { ...st, state, detail: detail[st.id] };
  });
}
