"use client";

import Link from "next/link";
import type { Outcome, Run } from "../../../_lib/api";
import { totalTokens, type RunState } from "../../../_lib/runState";
import { OUTCOME_LABEL, fmtTokens, hardCount, typeLabel } from "../../../_lib/swarm";
import { Badge, Card, ErrorNote, Icon, StatusChip, cx, type RunStatus } from "../../../_ui";
import { LiveTimer, Stat } from "../common";
import PrCard from "../PrCard";
import AgentLanes from "./AgentLanes";
import ArtifactsGallery from "./ArtifactsGallery";
import ClarifyForm from "./ClarifyForm";
import DiffPanel from "./DiffPanel";
import GateTable from "./GateTable";
import MergePanel from "./MergePanel";
import PlanCard from "./PlanCard";
import SwarmPipeline from "./SwarmPipeline";

export function swarmChip(state: RunState, run?: Run | null): { status: RunStatus; label?: string } {
  const outcome = (state.done?.outcome ?? run?.outcome ?? null) as Outcome | null;
  if (outcome === "complete" || outcome === "partial" || outcome === "needs_input") return { status: outcome };
  if (outcome === "blocked" || state.blocked) return { status: "blocked" };
  if (outcome === "failed" || (state.done && state.errors.length)) return { status: "failed" };
  if (state.done) return { status: "unsolved" };
  if (state.status === "reconnecting") return { status: "running", label: `Reconnecting (try ${state.attempt})` };
  if (state.status === "lost") return { status: "failed", label: "Connection lost" };
  if (state.status === "finished") return { status: state.errors.length ? "failed" : "unsolved" };
  if (state.status === "idle") return { status: "queued" };
  return { status: "running" };
}

function OutcomeBanner({ state, outcome }: { state: RunState; outcome: Outcome }) {
  const w = state.swarm;
  const hc = hardCount(w);
  const crit = state.done?.criteria ?? w.saved?.criteriaSummary ?? null;
  const unverified = ((crit as { unverified?: string[] } | null)?.unverified || []) as string[];
  const last = w.verifies[w.verifies.length - 1];
  const failing = last?.results.filter((r) => r.hard && r.status === "fail") || [];
  const advisory = (last?.results || w.saved?.criteriaSummary?.results || []).filter((r) => r.status === "advisory");
  const palette = {
    complete: ["border-primary/45 bg-primary/5", "text-primary", "check-circle"],
    partial: ["border-warning/45 bg-warning/5", "text-warning", "alert"],
    failed: ["border-error/45 bg-error/5", "text-error", "x-circle"],
    blocked: ["border-error/45 bg-error/5", "text-error", "ban"],
    needs_input: ["border-secondary/40 bg-secondary/5", "text-secondary", "info"],
  }[outcome];
  const head =
    outcome === "complete"
      ? `Complete: ${hc ? `${hc.pass}/${hc.total}` : "all"} hard gates passed`
      : outcome === "partial"
        ? `Partial: ${hc ? `${hc.pass}/${hc.total}` : "hard"} hard gates passed, some of the request is unverified`
        : outcome === "failed"
          ? `Failed: ${hc ? `${hc.pass}/${hc.total}` : "the"} hard gates passed`
          : outcome === "needs_input"
            ? "Needs input"
            : "Blocked";
  return (
    <div data-testid="run-result" data-outcome={outcome} className={cx("flex flex-col gap-2 rounded-xl border px-5 py-4", palette[0])}>
      <div className="flex items-start gap-3">
        <Icon name={palette[2]} size={22} className={cx("mt-0.5", palette[1])} />
        <div className="min-w-0">
          <div className={cx("text-[15px] font-semibold", palette[1])}>{head}</div>
          <p className="mt-0.5 text-[13px] leading-5 text-on-surface-variant">
            {outcome === "complete" && "The checks above decided, not the model. A person has to review and merge the pull request."}
            {outcome === "partial" && "Everything that could be checked mechanically passed. Read the list below before merging."}
            {outcome === "failed" && "Nothing was opened for merge. The best attempt and every check result are below."}
            {outcome === "needs_input" && "The planner could not size this task from the description alone."}
            {outcome === "blocked" && "A guard or policy stopped this run before it changed anything."}
          </p>
          {outcome === "failed" && failing.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-[13px] text-on-surface-variant">
              {failing.map((f) => (
                <li key={f.criterion_id}>
                  <span className="font-mono text-[12px] text-error">{f.criterion_id}</span>: {f.detail}
                </li>
              ))}
            </ul>
          )}
          {unverified.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-[13px] text-on-surface-variant" data-testid="unverified">
              {unverified.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          )}
          {advisory.length > 0 && outcome !== "failed" && (
            <p className="mt-2 text-[12.5px] text-on-surface-variant">
              Advisory, not gating:{" "}
              {advisory.map((a, i) => (
                <span key={a.criterion_id}>
                  {i ? " · " : ""}
                  {a.criterion_id} {a.score != null ? a.score.toFixed(2) : ""}
                </span>
              ))}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export type SwarmViewProps = {
  state: RunState;
  run?: Run | null;
  notice?: string | null;
  onRetry?: () => void;
  slackConfigured?: boolean | null;
  slackSent?: boolean | null;
};

export default function SwarmView({ state, run, notice, onRetry, slackConfigured = null, slackSent = null }: SwarmViewProps) {
  const w = state.swarm;
  const done = state.done;
  const finished = state.status === "finished" || !!done;
  const outcome = (done?.outcome ?? run?.outcome ?? null) as Outcome | null;
  const chip = swarmChip(state, run);
  const type = w.plan?.task_type ?? run?.taskType ?? done?.task_type;
  const hc = hardCount(w);
  const agentCount = Math.max(w.agentOrder.length, done?.agents?.spawned ?? 0);
  const peak = Math.max(w.peakParallel, done?.agents?.peak_parallel ?? 0);
  const crit = state.done?.criteria ?? w.saved?.criteriaSummary ?? null;
  const unverified = ((crit as { unverified?: string[] } | null)?.unverified || []) as string[];

  return (
    <div className="flex flex-col gap-5" data-testid="swarm-view">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-[22px] font-semibold leading-tight tracking-tight text-white [overflow-wrap:anywhere] sm:text-[26px]">{run?.task?.split("\n")[0] || state.repo?.full_name || "Task"}</h1>
          <StatusChip status={chip.status} label={chip.label} />
          {type && <Badge tone="info">{typeLabel(type)}</Badge>}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[12.5px] text-on-surface-variant">
          <span className="inline-flex items-center gap-1.5">
            <Icon name="github" size={14} />
            {run?.repo || state.repo?.full_name}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Icon name="git-branch" size={14} />
            {run?.branch || state.repo?.branch}
          </span>
          {run?.source && <span>via {run.source}</span>}
          {state.engine && <span>engine {state.engine}</span>}
          {run?.parentRunId && (
            <Link href={`/runs/${run.parentRunId}`} className="focus-ring rounded text-primary underline">
              continues an earlier run
            </Link>
          )}
        </div>
      </div>

      {notice && <ErrorNote tone="info">{notice}</ErrorNote>}

      <Card className="flex flex-col gap-5 p-5" data-testid="status-card">
        <SwarmPipeline state={state} />
        <span data-testid="run-status" className="sr-only">
          {chip.label ?? chip.status}
        </span>
        <div className="grid grid-cols-2 gap-4 border-t border-border pt-4 sm:grid-cols-5">
          <Stat label="Elapsed">
            <LiveTimer startedAt={state.startedAt} endedAt={state.endedAt} finalMs={done?.latency_ms} />
          </Stat>
          <Stat label="Agents spawned">{agentCount || "–"}</Stat>
          <Stat label="Peak parallel">{peak || "–"}</Stat>
          <Stat label="Tokens">{fmtTokens(done ? totalTokens(state) : (w.budget?.tokens_used ?? 0))}</Stat>
          <Stat label="Hard gates">{hc ? `${hc.pass}/${hc.total}` : "–"}</Stat>
        </div>
        {state.fromSnapshot && finished && <p className="text-[12px] text-on-surface-variant">Saved result. The agent timeline and per-round history show while a run is live; the plan, gates, artifacts and diff are kept.</p>}
      </Card>

      {state.errors.length > 0 && (
        <div data-testid="run-error" className="rounded-xl border border-error/40 bg-error/5 px-4 py-3.5">
          <div className="flex items-center gap-2 text-[14px] font-semibold text-error">
            <Icon name={state.blocked ? "ban" : "alert"} size={17} />
            {state.blocked ? "Blocked by guardrails" : "The run did not finish cleanly"}
          </div>
          {state.errors.map((e, i) => (
            <p key={i} className="mt-1.5 text-[13.5px] text-on-surface-variant">
              {e.stage && <span className="mr-1.5 font-mono text-[11.5px] text-error/80">[{e.stage}]</span>}
              {e.message}
            </p>
          ))}
        </div>
      )}
      {state.status === "lost" && (
        <ErrorNote tone="warning">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>Lost the live connection to this run. It may still be going on the server.</span>
            {onRetry && (
              <button onClick={onRetry} className="focus-ring rounded-md border border-warning/40 px-3 py-1 text-[12.5px] font-medium hover:bg-warning/10">
                Reconnect
              </button>
            )}
          </div>
        </ErrorNote>
      )}

      {run && (w.clarify || (outcome === "needs_input" && (finished || state.status === "lost"))) && (
        <ClarifyForm runId={run.id} questions={w.clarify || [{ id: "q1", text: "What should PatchLoop change, and how will you know it worked?" }]} />
      )}

      {finished && outcome && outcome !== "needs_input" && <OutcomeBanner state={state} outcome={outcome} />}
      {state.pr && run && <PrCard runId={run.id} pr={state.pr} repo={run.repo || state.repo?.full_name} outcome={outcome} unverified={unverified} />}
      {finished && run && state.pr && (
        <p className="flex items-center gap-2 text-[12.5px] text-on-surface-variant" data-testid="slack-indicator">
          <Icon name="slack" size={14} />
          {slackSent === true ? (
            <span className="text-primary">Slack notified when this run finished.</span>
          ) : slackConfigured === true ? (
            <span>Slack is set up; no message was sent for this run yet.</span>
          ) : slackConfigured === false ? (
            <span>
              Slack not set up.{" "}
              <Link href="/integrations" className="text-primary underline">
                Connect Slack
              </Link>{" "}
              to get a message when runs finish.
            </span>
          ) : (
            <span>Slack status unknown.</span>
          )}
        </p>
      )}

      {w.plan && <PlanCard plan={w.plan} finished={finished} />}
      {!w.clarify && <AgentLanes state={state} />}
      <MergePanel state={state} />
      <GateTable state={state} />
      {run && <ArtifactsGallery runId={run.id} artifacts={w.artifacts} finished={finished} />}
      <DiffPanel state={state} />
      {!w.plan && !w.clarify && state.status !== "lost" && !finished && (
        <p className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-[13.5px] text-on-surface-variant" role="status">
          Starting. The planner is reading the repository map and choosing how many agents this task needs.
        </p>
      )}
    </div>
  );
}
