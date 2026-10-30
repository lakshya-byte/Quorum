"use client";

import type { RunState } from "../../../_lib/runState";
import { stageWords } from "../../../_lib/swarm";
import { Icon, cx, type IconName } from "../../../_ui";

type StageState = "pending" | "active" | "done" | "skipped" | "warn";
type Stage = { id: string; label: string; icon: IconName; state: StageState; detail?: string };

const STATE_LABEL: Record<StageState, string> = { pending: "waiting", active: "in progress", done: "done", skipped: "skipped", warn: "needs attention" };

/** Stages adapt to the task type: the second and third labels change with the kind of work. */
export function swarmStages(s: RunState): Stage[] {
  const w = s.swarm;
  const type = w.plan?.task_type;
  const words = stageWords(type);
  const agents = w.agentOrder.map((id) => w.agents[id]);
  const finished = s.status === "finished" || !!s.done;
  const outcome = s.done?.outcome;
  const roleSeen = (r: string) => agents.some((a) => a.role === r);
  const roleActive = (r: string) => agents.some((a) => a.role === r && (a.status === "running" || a.status === "spawned"));
  const workers = agents.filter((a) => a.role === "worker");
  const ev = {
    plan: !!w.plan || !!w.clarify,
    spec: roleSeen("spec"),
    work: workers.length > 0,
    merge: w.merges.length > 0,
    verify: w.verifies.length > 0,
    review: roleSeen("reviewer") || !!s.guards.output,
    pr: !!s.pr,
  };
  const lastVerify = w.verifies[w.verifies.length - 1];
  const defs: { id: keyof typeof ev; label: string; icon: IconName; active: boolean; detail?: string }[] = [
    { id: "plan", label: w.clarify ? "Plan: needs input" : "Plan", icon: "crosshair", active: roleActive("planner") || roleActive("mapper"), detail: w.plan ? `${w.plan.criteria.length} criteria · ${w.plan.units.length} units` : undefined },
    { id: "spec", label: words.spec, icon: "flask", active: roleActive("spec"), detail: ev.spec ? "verifiers written" : undefined },
    { id: "work", label: words.work, icon: "sparkles", active: workers.some((a) => a.status === "running" || a.status === "spawned"), detail: workers.length ? `${workers.length} workers` : undefined },
    { id: "merge", label: "Merge", icon: "split", active: roleActive("integrator"), detail: w.merges.length ? w.merges[w.merges.length - 1].status : undefined },
    { id: "verify", label: "Verify", icon: "shield-check", active: false, detail: lastVerify ? (lastVerify.hard_pass ? "hard gates pass" : "gates failing") : undefined },
    { id: "review", label: "Review", icon: "eye", active: roleActive("reviewer") || roleActive("critic"), detail: undefined },
    { id: "pr", label: "PR", icon: "git-pr", active: false, detail: s.pr ? (s.pr.number ? `#${s.pr.number}` : "opened") : undefined },
  ];
  let reached = -1;
  defs.forEach((d, i) => {
    if (ev[d.id]) reached = i;
  });
  return defs.map((d, i) => {
    let state: StageState;
    if (finished) {
      if (outcome === "needs_input") state = i === 0 ? "warn" : "skipped";
      else if (ev[d.id]) state = d.id === "verify" && lastVerify && !lastVerify.hard_pass ? "warn" : "done";
      else if (i < reached && d.id !== "pr") state = d.id === "spec" || d.id === "merge" ? "skipped" : "done";
      else state = "skipped";
    } else if (i < reached) state = ev[d.id] || d.id !== "spec" ? "done" : "skipped";
    else if (i === reached) state = d.active ? "active" : "done";
    else if (i === reached + 1 && s.status !== "idle") state = "active";
    else state = "pending";
    if (!finished && i === reached && d.id === "verify" && lastVerify && !lastVerify.hard_pass) state = "warn";
    return { id: d.id, label: d.label, icon: d.icon, state, detail: d.detail };
  });
}

export default function SwarmPipeline({ state }: { state: RunState }) {
  const stages = swarmStages(state);
  return (
    <ol className="grid grid-cols-4 gap-x-1 gap-y-4 sm:grid-cols-7" aria-label="Run pipeline" data-testid="pipeline">
      {stages.map((s, i) => (
        <li key={s.id} data-stage={s.id} data-state={s.state} className="relative flex min-w-0 flex-col items-center gap-1.5 text-center">
          {i < stages.length - 1 && (
            <span
              aria-hidden
              className={cx(
                "absolute left-[calc(50%+18px)] right-[calc(-50%+18px)] top-[17px] hidden h-px sm:block",
                s.state === "done" ? "bg-primary/60" : s.state === "active" ? "flow-line bg-transparent [background:repeating-linear-gradient(90deg,var(--primary)_0_4px,transparent_4px_8px)]" : "bg-border-strong"
              )}
            />
          )}
          <span
            className={cx(
              "relative z-10 flex h-[34px] w-[34px] items-center justify-center rounded-full border transition-colors",
              s.state === "done" && "border-primary/60 bg-primary/15 text-primary",
              s.state === "active" && "border-secondary bg-secondary/10 text-secondary shadow-[0_0_0_4px_rgba(6,182,212,0.12)]",
              s.state === "warn" && "border-warning/60 bg-warning/10 text-warning",
              s.state === "pending" && "border-border-strong bg-bg text-text-subtle",
              s.state === "skipped" && "border-border bg-bg text-text-subtle opacity-60"
            )}
          >
            {s.state === "done" ? <Icon name="check" size={16} strokeWidth={2.5} /> : <Icon name={s.icon} size={16} className={s.state === "active" ? "animate-pulse" : ""} />}
          </span>
          <span className={cx("text-[12px] font-medium", s.state === "pending" || s.state === "skipped" ? "text-text-subtle" : "text-white")}>{s.label}</span>
          <span className="sr-only">{STATE_LABEL[s.state]}</span>
          <span className="hidden min-h-4 max-w-full truncate text-[11px] text-on-surface-variant sm:block" title={s.detail}>
            {s.detail || ""}
          </span>
        </li>
      ))}
    </ol>
  );
}
