"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { Bug } from "../../_lib/api";
import { totalTokens, type GuardStage, type RunState } from "../../_lib/runState";
import AttemptTree from "./AttemptTree";
import NodePanel from "./NodePanel";
import { fmtMs } from "./NodeCard";

const GUARD_LABEL: Record<GuardStage, string> = { input: "Input guard", policy: "Policy gate", output: "Output guard" };

function LiveTimer({ startedAt, endedAt, finalMs }: { startedAt: number | null; endedAt: number | null; finalMs?: number }) {
  const [now, setNow] = useState(() => (typeof performance !== "undefined" ? performance.now() : 0));
  const running = startedAt != null && endedAt == null && finalMs == null;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(t);
  }, [running]);
  let ms: number | null = null;
  if (finalMs != null) ms = finalMs;
  else if (startedAt != null) ms = (endedAt ?? now) - startedAt;
  return <span className="tabular-nums">{ms == null ? "–" : `${(Math.max(0, ms) / 1000).toFixed(1)}s`}</span>;
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col min-w-0">
      <span className="text-[9.5px] font-mono uppercase tracking-wider text-on-surface-variant/80">{label}</span>
      <span className="text-[14px] font-mono text-white tabular-nums">{children}</span>
    </div>
  );
}

function StatusPill({ state }: { state: RunState }) {
  const { status, done, blocked, errors } = state;
  let label = "Idle";
  let cls = "bg-surface-container-high text-on-surface-variant border-outline-variant/60";
  let dot = "bg-on-surface-variant";
  let pulse = false;
  if (blocked && (!done || !done.solved)) {
    label = "Blocked";
    cls = "bg-error/10 text-error border-error/40";
    dot = "bg-error";
  } else if (done?.solved) {
    label = "Solved";
    cls = "bg-primary/10 text-primary border-primary/40";
    dot = "bg-primary";
  } else if (done && !done.solved) {
    label = "Unsolved";
    cls = "bg-amber-400/10 text-amber-300 border-amber-400/40";
    dot = "bg-amber-400";
  } else if (errors.length && status === "finished") {
    label = "Failed";
    cls = "bg-error/10 text-error border-error/40";
    dot = "bg-error";
  } else if (status === "live" || status === "connecting") {
    label = status === "connecting" ? "Connecting" : "Live";
    cls = "bg-primary/10 text-primary border-primary/40";
    dot = "bg-primary";
    pulse = true;
  } else if (status === "reconnecting") {
    label = `Reconnecting (try ${state.attempt})`;
    cls = "bg-amber-400/10 text-amber-300 border-amber-400/40";
    dot = "bg-amber-400";
    pulse = true;
  } else if (status === "lost") {
    label = "Connection lost";
    cls = "bg-error/10 text-error border-error/40";
    dot = "bg-error";
  } else if (status === "finished") {
    label = "Finished";
  }
  return (
    <span data-testid="run-status" className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-mono text-[11px] font-medium ${cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dot} ${pulse ? "animate-pulse" : ""}`} />
      {label}
    </span>
  );
}

function GuardPill({ stage, state }: { stage: GuardStage; state: RunState }) {
  const g = state.guards[stage];
  const finished = state.status === "finished" || !!state.done;
  let cls = "border-outline-variant/60 text-on-surface-variant bg-surface-container-low";
  let icon = "radio_button_unchecked";
  let text = finished ? "not run" : "pending";
  if (g?.verdict === "pass") {
    cls = "border-primary/40 text-primary bg-primary/10";
    icon = "verified_user";
    text = "pass";
  } else if (g?.verdict === "block") {
    cls = "border-error/50 text-error bg-error/10";
    icon = "gpp_bad";
    text = "block";
  }
  return (
    <span
      title={g?.reasons?.length ? g.reasons.join("\n") : undefined}
      data-testid={`guard-${stage}`}
      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border font-mono text-[11px] ${cls}`}
    >
      <span className="material-symbols-outlined text-[14px]">{icon}</span>
      <span className="text-on-surface/90">{GUARD_LABEL[stage]}</span>
      <span className="font-semibold">{text}</span>
      {g?.latency_ms != null && <span className="opacity-70">{fmtMs(g.latency_ms)}</span>}
    </span>
  );
}

export type RunViewProps = {
  state: RunState;
  bug?: Bug | null;
  /** Rendered in the result banner once the run is solved. */
  solvedActions?: ReactNode;
  /** Shown above the tree when the stream gave up. */
  onRetry?: () => void;
  notice?: string | null;
};

export default function RunView({ state, bug, solvedActions, onRetry, notice }: RunViewProps) {
  const [selected, setSelected] = useState<number | null>(null);
  const onSelect = useCallback((id: number) => setSelected(id), []);
  const onClose = useCallback(() => setSelected(null), []);

  const done = state.done;
  const bestId = done?.best ?? null;
  const solved = !!done?.solved;
  const live = state.status === "live" || state.status === "connecting" || state.status === "reconnecting";
  const ttfn =
    done?.time_to_first_node_ms ??
    (state.firstNodeAt != null && state.startedAt != null ? state.firstNodeAt - state.startedAt : null);
  const best = bestId != null ? state.nodes[bestId] : undefined;
  const original = state.nodes[0]?.code ?? state.nodes[state.children[-1]?.[0] ?? -999]?.code;
  const hasGuards = Object.keys(state.guards).length > 0 || (state.engine === "graph" && !state.fromSnapshot);
  const selNode = selected != null ? state.nodes[selected] : undefined;
  const nonGuardErrors = state.errors;

  return (
    <div className="flex flex-col gap-4">
      {bug && (
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl sm:text-2xl text-white font-semibold tracking-tight">{bug.title}</h1>
            <span className="text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border border-outline-variant/60 text-on-surface-variant">
              {bug.tier}
            </span>
          </div>
          <p className="text-[13.5px] leading-relaxed text-on-surface-variant max-w-3xl">{bug.issue}</p>
        </div>
      )}

      {notice && (
        <div className="rounded-lg border border-secondary/30 bg-secondary/5 px-3.5 py-2.5 text-[13px] text-secondary flex items-start gap-2">
          <span className="material-symbols-outlined text-[16px] mt-px">info</span>
          {notice}
        </div>
      )}

      {/* Status bar */}
      <div className="rounded-xl border border-outline-variant/60 bg-[#0b0e15] px-3.5 sm:px-4 py-3 flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill state={state} />
          {state.mode && (
            <span className="font-mono text-[10.5px] px-2 py-0.5 rounded border border-outline-variant/60 text-on-surface-variant">
              mode: <span className="text-white">{state.mode}</span>
            </span>
          )}
          {state.engine && (
            <span className="font-mono text-[10.5px] px-2 py-0.5 rounded border border-outline-variant/60 text-on-surface-variant">
              engine: <span className="text-white">{state.engine === "graph" ? "agent team" : state.engine}</span>
            </span>
          )}
          {state.fromSnapshot && state.status === "finished" && (
            <span className="font-mono text-[10.5px] text-on-surface-variant">saved result · guard, triage and critic details are shown while a run is live</span>
          )}
        </div>
        {hasGuards && (
          <div className="flex flex-wrap gap-1.5">
            {(["input", "policy", "output"] as GuardStage[]).map((s) => (
              <GuardPill key={s} stage={s} state={state} />
            ))}
          </div>
        )}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 pt-2 border-t border-outline-variant/40">
          <Stat label="Elapsed">
            <LiveTimer startedAt={state.startedAt} endedAt={state.endedAt} finalMs={done?.latency_ms} />
          </Stat>
          <Stat label="First attempt">{ttfn != null ? fmtMs(ttfn) : "–"}</Stat>
          <Stat label="Tokens">{totalTokens(state).toLocaleString()}</Stat>
          <Stat label="Attempts">{Math.max(0, state.order.length - (state.nodes[0] ? 1 : 0))}</Stat>
          <Stat label="Round">{state.depth || "–"}</Stat>
        </div>
      </div>

      {/* Errors and blocked */}
      {nonGuardErrors.length > 0 && (
        <div data-testid="run-error" className="rounded-xl border border-error/40 bg-error/5 px-4 py-3 flex flex-col gap-1.5">
          <div className="flex items-center gap-2 text-error text-[14px] font-medium">
            <span className="material-symbols-outlined text-[18px]">{state.blocked ? "gpp_bad" : "error"}</span>
            {state.blocked ? "Blocked by guardrails" : "The run failed"}
          </div>
          {nonGuardErrors.map((e, i) => (
            <p key={i} className="text-[13px] text-on-surface-variant">
              {e.stage && <span className="font-mono text-[11px] text-error/80 mr-1.5">[{e.stage}]</span>}
              {e.message}
            </p>
          ))}
          {state.guards.input?.verdict === "block" && (state.guards.input.reasons || []).length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-[12.5px] text-on-surface-variant">
              {state.guards.input.reasons!.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {state.status === "lost" && (
        <div className="rounded-xl border border-amber-400/40 bg-amber-400/5 px-4 py-3 flex flex-wrap items-center justify-between gap-2 text-[13px] text-amber-200">
          <span>Lost the live connection to this run. The run may still be going on the server.</span>
          {onRetry && (
            <button onClick={onRetry} className="px-3 py-1.5 rounded-md bg-amber-400/15 border border-amber-400/40 font-mono text-[12px] hover:bg-amber-400/25">
              Reconnect
            </button>
          )}
        </div>
      )}

      {/* Triage */}
      {state.triage && (
        <details open className="group rounded-xl border border-outline-variant/60 bg-surface-container-low">
          <summary className="cursor-pointer list-none px-4 py-3 flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-[13px] text-white font-medium">
              <span className="material-symbols-outlined text-[17px] text-secondary">troubleshoot</span>
              Triage
              <span className="font-mono text-[11px] text-on-surface-variant font-normal">
                cause + {state.triage.strategies.length} strategies
              </span>
            </span>
            <span className="material-symbols-outlined text-[18px] text-on-surface-variant transition-transform group-open:rotate-180">expand_more</span>
          </summary>
          <div className="px-4 pb-4 flex flex-col gap-3">
            <p className="text-[13.5px] leading-relaxed text-on-surface-variant">{state.triage.cause}</p>
            <ol className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {state.triage.strategies.map((s, i) => (
                <li key={i} className="rounded-lg border border-secondary/25 bg-secondary/5 px-3 py-2 text-[12.5px] text-on-surface flex gap-2">
                  <span className="font-mono text-secondary">{i + 1}</span>
                  {s}
                </li>
              ))}
            </ol>
          </div>
        </details>
      )}

      {/* Result */}
      {done && !state.blocked && (
        <div
          data-testid="run-result"
          className={`rounded-xl border px-4 py-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
            solved ? "border-primary/50 bg-primary/5" : "border-amber-400/40 bg-amber-400/5"
          }`}
        >
          <div className="flex items-start gap-2.5">
            <span className={`material-symbols-outlined text-[22px] ${solved ? "text-primary" : "text-amber-300"}`}>
              {solved ? "task_alt" : "report"}
            </span>
            <div>
              <div className={`text-[14px] font-medium ${solved ? "text-primary" : "text-amber-200"}`}>
                {solved
                  ? `Fixed: attempt #${bestId} passes ${best ? `${best.passed}/${best.total}` : "all"} tests`
                  : "No attempt passed every test"}
              </div>
              <div className="text-[12.5px] text-on-surface-variant">
                {solved
                  ? "Tests decided, not the AI. A pull request needs a human to review and merge it."
                  : best
                    ? `Best attempt #${best.id} passes ${best.passed}/${best.total}. Nothing is proposed for merge; an engineer should take a look.`
                    : "Nothing is proposed for merge."}
              </div>
            </div>
          </div>
          {solved && solvedActions && <div className="flex flex-wrap gap-2 sm:justify-end">{solvedActions}</div>}
        </div>
      )}

      {/* Tree */}
      <section className="rounded-xl border border-outline-variant/60 bg-[#090c12] p-3 sm:p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-on-surface-variant flex items-center gap-1.5">
            <span className="material-symbols-outlined text-[16px] text-primary">account_tree</span>
            Attempts
          </h2>
          <div className="hidden sm:flex items-center gap-3 font-mono text-[10.5px] text-on-surface-variant">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-primary" />all pass</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400" />some</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-error" />none</span>
            <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm border border-dashed border-amber-400" />flagged</span>
          </div>
        </div>
        {state.blocked && state.order.length === 0 ? (
          <p className="text-[13px] text-on-surface-variant py-6 text-center">No attempts: the request never reached an agent.</p>
        ) : (
          <AttemptTree state={state} bestId={solved ? bestId : null} selectedId={selected} onSelect={onSelect} live={live} />
        )}
        {state.order.length > 0 && (
          <p className="mt-4 text-[11.5px] text-on-surface-variant/80 font-mono">Click an attempt to see its code, diff, test output and security result.</p>
        )}
      </section>

      {selNode && <NodePanel node={selNode} original={original} isBest={solved && bestId === selNode.id} onClose={onClose} />}
    </div>
  );
}
