"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { Bug, Run } from "../../_lib/api";
import { changedFileCount } from "../../_lib/unified";
import { isRepoRun, totalTokens, type GuardStage, type RunState } from "../../_lib/runState";
import { Badge, Card, ErrorNote, Icon, StatusChip, cx, type RunStatus } from "../../_ui";
import AttemptTree from "./AttemptTree";
import NodePanel from "./NodePanel";
import { fmtMs } from "./NodeCard";
import Pipeline from "./Pipeline";
import PrCard from "./PrCard";

const GUARD_LABEL: Record<GuardStage, string> = { input: "Input guard", policy: "Policy gate", output: "Output guard" };

function LiveTimer({ startedAt, endedAt, finalMs }: { startedAt: number | null; endedAt: number | null; finalMs?: number }) {
  const [now, setNow] = useState(() => (typeof performance !== "undefined" ? performance.now() : 0));
  const running = startedAt != null && endedAt == null && finalMs == null;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(performance.now()), 200);
    return () => clearInterval(t);
  }, [running]);
  let ms: number | null = null;
  if (finalMs != null) ms = finalMs;
  else if (startedAt != null) ms = (endedAt ?? now) - startedAt;
  return <span className="tabular-nums">{ms == null ? "–" : `${(Math.max(0, ms) / 1000).toFixed(1)}s`}</span>;
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-[11.5px] text-on-surface-variant">{label}</span>
      <span className="text-[15px] font-semibold tabular-nums text-white">{children}</span>
    </div>
  );
}

export function runChip(state: RunState): { status: RunStatus; label?: string } {
  const { status, done, blocked } = state;
  if (blocked && (!done || !done.solved)) return { status: "blocked" };
  if (done?.solved) return { status: "solved" };
  if (state.errors.length && done) return { status: "failed" };
  if (done) return { status: "unsolved" };
  if (status === "reconnecting") return { status: "running", label: `Reconnecting (try ${state.attempt})` };
  if (status === "lost") return { status: "failed", label: "Connection lost" };
  if (status === "finished") return { status: state.errors.length ? "failed" : "unsolved" };
  if (status === "idle") return { status: "queued" };
  return { status: "running" };
}

function GuardPill({ stage, state }: { stage: GuardStage; state: RunState }) {
  const g = state.guards[stage];
  const finished = state.status === "finished" || !!state.done;
  const tone = g?.verdict === "pass" ? "success" : g?.verdict === "block" ? "danger" : "neutral";
  const text = g ? (g.verdict === "pass" ? "pass" : "block") : finished ? "not run" : "pending";
  return (
    <span title={g?.reasons?.length ? g.reasons.join("\n") : undefined} data-testid={`guard-${stage}`}>
      <Badge tone={tone} icon={g?.verdict === "block" ? "ban" : g ? "shield-check" : "shield"}>
        {GUARD_LABEL[stage]}: {text}
        {g?.latency_ms != null ? ` · ${fmtMs(g.latency_ms)}` : ""}
      </Badge>
    </span>
  );
}

export type RunViewProps = {
  state: RunState;
  bug?: Bug | null;
  /** The saved run record; enables the repo header and the PR card. */
  run?: Run | null;
  /** Rendered in the result banner once the run is solved (bug runs). */
  solvedActions?: ReactNode;
  onRetry?: () => void;
  notice?: string | null;
  /** Whether a Slack webhook is configured for this user (null = unknown / not shown). */
  slackConfigured?: boolean | null;
};

export default function RunView({ state, bug, run, solvedActions, onRetry, notice, slackConfigured = null }: RunViewProps) {
  const [selected, setSelected] = useState<number | null>(null);
  const onSelect = useCallback((id: number) => setSelected(id), []);
  const onClose = useCallback(() => setSelected(null), []);

  const done = state.done;
  const bestId = done?.best ?? null;
  const solved = !!done?.solved;
  const live = state.status === "live" || state.status === "connecting" || state.status === "reconnecting";
  const ttfn = done?.time_to_first_node_ms ?? (state.firstNodeAt != null && state.startedAt != null ? state.firstNodeAt - state.startedAt : null);
  const best = bestId != null ? state.nodes[bestId] : undefined;
  const original = state.nodes[0]?.code ?? state.nodes[state.children[-1]?.[0] ?? -999]?.code;
  const repoRun = isRepoRun(state) || run?.kind === "repo";
  const hasGuards = Object.keys(state.guards).length > 0 || (state.engine === "graph" && !state.fromSnapshot);
  const selNode = selected != null ? state.nodes[selected] : undefined;
  const chip = runChip(state);
  const finished = state.status === "finished" || !!done;
  const filesChanged = run?.filesChanged ?? (best?.files ? changedFileCount(best) : null);

  return (
    <div className="flex flex-col gap-5">
      {repoRun ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-[22px] font-semibold leading-tight tracking-tight text-white sm:text-[26px]">{run?.task || state.repo?.full_name || "Repository fix"}</h1>
            <StatusChip status={chip.status} label={chip.label} />
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
            {run?.traceId && <span title="Trace id">trace {run.traceId}</span>}
            {run?.langsmithUrl && (
              <a href={run.langsmithUrl} target="_blank" rel="noopener noreferrer" className="text-secondary underline">
                LangSmith trace
              </a>
            )}
          </div>
        </div>
      ) : (
        bug && (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-[22px] font-semibold leading-tight tracking-tight text-white sm:text-[26px]">{bug.title}</h1>
              <StatusChip status={chip.status} label={chip.label} />
              {bug.tier && <Badge mono>{bug.tier}</Badge>}
            </div>
            <p className="max-w-3xl text-[14px] leading-6 text-on-surface-variant">{bug.issue}</p>
          </div>
        )
      )}

      {notice && <ErrorNote tone="info">{notice}</ErrorNote>}

      <Card className="flex flex-col gap-5 p-5" data-testid="status-card">
        {repoRun && <Pipeline state={state} />}
        <div className={cx("flex flex-wrap items-center gap-2", repoRun && "border-t border-border pt-4")}>
          <span data-testid="run-status" className="sr-only">
            {chip.label ?? chip.status}
          </span>
          {!repoRun && <StatusChip status={chip.status} label={chip.label} />}
          {state.mode && <Badge mono>mode {state.mode}</Badge>}
          {state.engine && <Badge mono>{state.engine === "graph" ? "agent team" : state.engine}</Badge>}
          {hasGuards && (["input", "policy", "output"] as GuardStage[]).map((s) => <GuardPill key={s} stage={s} state={state} />)}
          {state.fromSnapshot && finished && <span className="text-[12px] text-on-surface-variant">Saved result. Guard, triage and critic details show while a run is live.</span>}
        </div>
        <div className="grid grid-cols-2 gap-4 border-t border-border pt-4 sm:grid-cols-5">
          <Stat label="Elapsed">
            <LiveTimer startedAt={state.startedAt} endedAt={state.endedAt} finalMs={done?.latency_ms} />
          </Stat>
          <Stat label="First attempt">{ttfn != null ? fmtMs(ttfn) : "–"}</Stat>
          <Stat label="Tokens">{totalTokens(state).toLocaleString()}</Stat>
          <Stat label="Attempts">{Math.max(0, state.order.length - (state.nodes[0] ? 1 : 0))}</Stat>
          <Stat label={repoRun ? "Files changed" : "Round"}>{repoRun ? (filesChanged ?? "–") : state.depth || "–"}</Stat>
        </div>
      </Card>

      {repoRun && state.repro && (
        <Card className="p-4" data-testid="repro-card">
          <div className="flex items-start gap-3">
            <Icon name="bug" size={18} className={state.repro.failed_on_original ? "mt-0.5 text-primary" : "mt-0.5 text-warning"} />
            <div className="min-w-0 flex-1">
              <p className="text-[13.5px] font-medium text-white">
                {state.repro.failed_on_original
                  ? `Reproducer ${state.repro.test_name ? `"${state.repro.test_name}" ` : ""}fails on the original code`
                  : "Could not reproduce the bug with a new test, using the existing suite only"}
              </p>
              {state.repro.path && <p className="font-mono text-[12px] text-on-surface-variant">{state.repro.path}</p>}
              {state.repro.output_tail && (
                <pre className="mt-2 max-h-32 overflow-auto rounded-md border border-border bg-bg p-2.5 font-mono text-[11.5px] leading-5 text-on-surface-variant">{state.repro.output_tail}</pre>
              )}
            </div>
          </div>
        </Card>
      )}

      {state.errors.length > 0 && (
        <div data-testid="run-error" className="rounded-xl border border-error/40 bg-error/5 px-4 py-3.5">
          <div className="flex items-center gap-2 text-[14px] font-semibold text-error">
            <Icon name={state.blocked ? "ban" : "alert"} size={17} />
            {state.blocked ? "Blocked by guardrails" : "The run failed"}
          </div>
          {state.errors.map((e, i) => (
            <p key={i} className="mt-1.5 text-[13.5px] text-on-surface-variant">
              {e.stage && <span className="mr-1.5 font-mono text-[11.5px] text-error/80">[{e.stage}]</span>}
              {e.message}
            </p>
          ))}
          {state.guards.input?.verdict === "block" && (state.guards.input.reasons || []).length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-[13px] text-on-surface-variant">
              {state.guards.input.reasons!.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
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

      {state.triage && (
        <details open className="group rounded-xl border border-border bg-panel">
          <summary className="focus-ring flex cursor-pointer list-none items-center justify-between gap-2 rounded-xl px-5 py-3.5">
            <span className="flex items-center gap-2 text-[14px] font-semibold text-white">
              <Icon name="crosshair" size={16} className="text-secondary" />
              Triage
              <span className="text-[12px] font-normal text-on-surface-variant">likely cause and {state.triage.strategies.length} strategies</span>
            </span>
            <Icon name="chevron-down" size={16} className="text-on-surface-variant transition-transform group-open:rotate-180" />
          </summary>
          <div className="flex flex-col gap-3 px-5 pb-5">
            <p className="text-[14px] leading-6 text-on-surface-variant">{state.triage.cause}</p>
            <ol className="grid grid-cols-1 gap-2 md:grid-cols-3">
              {state.triage.strategies.map((s, i) => (
                <li key={i} className="flex gap-2 rounded-lg border border-border bg-surface-container-low px-3 py-2.5 text-[13px] leading-5 text-on-surface">
                  <span className="font-mono text-secondary">{i + 1}</span>
                  {s}
                </li>
              ))}
            </ol>
          </div>
        </details>
      )}

      {done && !state.blocked && (
        <div
          data-testid="run-result"
          className={cx(
            "flex flex-col justify-between gap-3 rounded-xl border px-5 py-4 sm:flex-row sm:items-center",
            solved ? "border-primary/45 bg-primary/5" : "border-warning/40 bg-warning/5"
          )}
        >
          <div className="flex items-start gap-3">
            <Icon name={solved ? "check-circle" : "alert"} size={22} className={solved ? "text-primary" : "text-warning"} />
            <div>
              <div className={cx("text-[15px] font-semibold", solved ? "text-primary" : "text-warning")}>
                {solved ? `Fixed: attempt #${bestId} passes ${best ? `${best.passed}/${best.total}` : "all"} tests` : "No attempt passed every test"}
              </div>
              <div className="mt-0.5 text-[13px] leading-5 text-on-surface-variant">
                {solved
                  ? "Your tests decided, not the AI. A person has to review and merge the pull request."
                  : best
                    ? `Best attempt #${best.id} passes ${best.passed}/${best.total}. Nothing was opened for merge; an engineer should take a look.`
                    : "Nothing was opened for merge."}
              </div>
            </div>
          </div>
          {solved && solvedActions && <div className="flex flex-wrap gap-2 sm:justify-end">{solvedActions}</div>}
        </div>
      )}

      {repoRun && state.pr && run && <PrCard runId={run.id} pr={state.pr} repo={run.repo || state.repo?.full_name} />}
      {repoRun && finished && run && (
        <p className="flex items-center gap-2 text-[12.5px] text-on-surface-variant" data-testid="slack-indicator">
          <Icon name="slack" size={14} />
          {state.slackSent === true || (slackConfigured && state.slackSent !== false) ? (
            <span className="text-primary">Slack notified when this run finished.</span>
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

      <section aria-labelledby="attempts-h">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="attempts-h" className="flex items-center gap-2 text-[15px] font-semibold text-white">
            <Icon name="split" size={16} className="text-primary" />
            Attempts
          </h2>
          <div className="hidden items-center gap-3 text-[12px] text-on-surface-variant sm:flex">
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-primary" />all pass</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-warning" />some</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-error" />none</span>
          </div>
        </div>
        <Card className="p-3 sm:p-5">
          {state.blocked && state.order.length === 0 ? (
            <p className="py-6 text-center text-[13px] text-on-surface-variant">No attempts: the request never reached an agent.</p>
          ) : (
            <AttemptTree state={state} bestId={solved ? bestId : null} selectedId={selected} onSelect={onSelect} live={live} />
          )}
          {state.order.length > 0 && <p className="mt-4 text-[12px] text-text-subtle">Select an attempt to see its diff, files, test output and security result.</p>}
        </Card>
      </section>

      {selNode && <NodePanel node={selNode} original={original} isBest={solved && bestId === selNode.id} onClose={onClose} />}
    </div>
  );
}
