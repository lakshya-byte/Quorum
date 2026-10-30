"use client";

import { memo } from "react";
import type { RunState } from "../../../_lib/runState";
import type { AgentState, UnitState } from "../../../_lib/swarm";
import { Badge, Icon, cx, type Tone } from "../../../_ui";
import { shortModel } from "../NodeCard";
import BudgetMeter from "./BudgetMeter";

const AGENT_TONE: Record<string, { tone: Tone; label: string }> = {
  spawned: { tone: "neutral", label: "starting" },
  running: { tone: "info", label: "running" },
  done: { tone: "success", label: "done" },
  failed: { tone: "danger", label: "failed" },
  cancelled: { tone: "neutral", label: "cancelled" },
};
const UNIT_TONE: Record<string, { tone: Tone; label: string }> = {
  pending: { tone: "neutral", label: "pending" },
  running: { tone: "info", label: "running" },
  passed: { tone: "success", label: "passed" },
  failed: { tone: "danger", label: "failed" },
  cancelled: { tone: "neutral", label: "cancelled" },
  merged: { tone: "success", label: "merged" },
};

function StatusDot({ status }: { status: string }) {
  if (status === "running" || status === "spawned") return <Icon name="loader" size={14} className="animate-spin text-secondary" />;
  if (status === "done") return <Icon name="check-circle" size={14} className="text-primary" />;
  if (status === "failed") return <Icon name="x-circle" size={14} className="text-error" />;
  return <Icon name="ban" size={14} className="text-text-subtle" />;
}

export const AgentRow = memo(function AgentRow({ a }: { a: AgentState }) {
  const last = a.tools[0];
  const st = AGENT_TONE[a.status] || AGENT_TONE.running;
  return (
    <li
      data-agent={a.id}
      data-status={a.status}
      className={cx("flex flex-col gap-1 rounded-lg border px-3 py-2 sm:flex-row sm:items-center sm:gap-3", a.status === "failed" ? "border-error/35 bg-error/5" : "border-border bg-surface-container-low", a.status === "cancelled" && "opacity-70")}
    >
      <div className="flex min-w-0 items-center gap-2 sm:w-[240px] sm:shrink-0">
        <StatusDot status={a.status} />
        <span className={cx("truncate font-mono text-[12.5px]", a.status === "cancelled" ? "text-on-surface-variant line-through decoration-text-subtle/60" : "text-white")}>
          {a.role}
          {a.variant ? ` · variant ${a.variant}` : ""}
        </span>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>
      <div className="min-w-0 flex-1 text-[12.5px] leading-5 text-on-surface-variant">
        {a.status === "running" || a.status === "spawned" ? (
          last ? (
            <span className="block truncate font-mono" title={`${last.name} ${last.target || ""}`}>
              <span className={last.ok ? "text-secondary" : "text-error"}>{last.name}</span> {last.target}
              {last.note ? <span className={last.ok ? "text-text-subtle" : "text-error"}> ({last.note})</span> : null}
            </span>
          ) : (
            <span className="text-text-subtle">starting in an isolated sandbox</span>
          )
        ) : (
          <span className="block truncate" title={a.summary}>
            {a.summary || (a.status === "cancelled" ? "Cancelled." : "")}
          </span>
        )}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[11.5px] text-text-subtle">
        {a.model && <span title={a.model}>{shortModel(a.model)}</span>}
        <span title="tool calls">{a.steps ?? a.toolCount} steps</span>
        {a.isolation && <span title="where it runs">{a.isolation}</span>}
      </div>
    </li>
  );
});

function UnitLane({ unit, title, files, agents, state }: { unit: UnitState | undefined; title: string; files: string[]; agents: AgentState[]; state: { id: string } }) {
  const st = UNIT_TONE[unit?.status || "pending"];
  return (
    <section className="min-w-0 rounded-xl border border-border bg-panel" data-unit={state.id} data-unit-status={unit?.status || "pending"} aria-label={`Unit ${state.id}: ${title}`}>
      <header className="flex flex-wrap items-center gap-2 border-b border-border px-3.5 py-2.5">
        <span className="font-mono text-[12px] text-secondary">{state.id}</span>
        <h3 className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-white">{title}</h3>
        {unit?.winner_variant && <span className="text-[12px] text-on-surface-variant">variant {unit.winner_variant} won</span>}
        <Badge tone={st.tone}>{st.label}</Badge>
      </header>
      {files.length > 0 && <p className="truncate px-3.5 pt-2 font-mono text-[11.5px] text-text-subtle" title={files.join(", ")}>{files.join(", ")}</p>}
      <ul className="flex flex-col gap-1.5 p-3">
        {agents.length === 0 ? <li className="px-1 text-[12.5px] text-text-subtle">Waiting for its dependencies.</li> : agents.map((a) => <AgentRow key={a.id} a={a} />)}
      </ul>
    </section>
  );
}

export default function AgentLanes({ state }: { state: RunState }) {
  const w = state.swarm;
  const agents = w.agentOrder.map((id) => w.agents[id]);
  const unitIds: string[] = [...(w.plan?.units.map((u) => u.id) || [])];
  // saved runs: peak/spawned come from the saved counts
  for (const a of agents) if (a.unit_id && !unitIds.includes(a.unit_id)) unitIds.push(a.unit_id);
  for (const id of Object.keys(w.units)) if (!unitIds.includes(id)) unitIds.push(id);
  const support = agents.filter((a) => !a.unit_id);
  const peak = Math.max(w.peakParallel, state.done?.agents?.peak_parallel ?? 0);
  const spawned = Math.max(agents.length, state.done?.agents?.spawned ?? 0);
  const running = agents.filter((a) => a.status === "running" || a.status === "spawned").length;
  const live = !state.done && state.status !== "finished";

  return (
    <section aria-labelledby="lanes-h" className="flex flex-col gap-3" data-testid="agent-lanes">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="lanes-h" className="flex items-center gap-2 text-[15px] font-semibold text-white">
          <Icon name="split" size={16} className="text-primary" />
          Agent lanes
        </h2>
        <p className="text-[12.5px] text-on-surface-variant">
          <span data-testid="agents-count">{spawned}</span> agents spawned · peak <span data-testid="peak-parallel">{peak}</span> in parallel{live && running > 0 ? ` · ${running} running now` : ""}
        </p>
      </div>
      <div className="rounded-xl border border-border bg-panel p-4">
        <BudgetMeter state={state} />
      </div>
      {unitIds.length === 0 && support.length === 0 && (
        <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-[13px] text-on-surface-variant">
          {state.fromSnapshot ? "Saved run: the per-agent timeline is only shown while a run streams. Counts above are kept." : "Agents appear here as the planner spawns them."}
        </p>
      )}
      <div className={cx("grid grid-cols-1 gap-3 2xl:grid-cols-2", state.fromSnapshot && agents.length === 0 && "hidden")}>
        {unitIds.map((id) => {
          const pu = w.plan?.units.find((u) => u.id === id);
          const files = pu?.scope_files || w.units[id]?.files || [];
          return <UnitLane key={id} state={{ id }} unit={w.units[id]} title={pu?.title || (id.startsWith("u") ? "Repair unit" : id)} files={files} agents={agents.filter((a) => a.unit_id === id)} />;
        })}
        {support.length > 0 && (
          <section className="min-w-0 rounded-xl border border-border bg-panel 2xl:col-span-2" aria-label="Support agents">
            <header className="border-b border-border px-3.5 py-2.5">
              <h3 className="text-[13.5px] font-medium text-white">Planner, spec, integrator and review agents</h3>
            </header>
            <ul className="grid gap-1.5 p-3 lg:grid-cols-2">
              {support.map((a) => (
                <AgentRow key={a.id} a={a} />
              ))}
            </ul>
          </section>
        )}
      </div>
    </section>
  );
}
