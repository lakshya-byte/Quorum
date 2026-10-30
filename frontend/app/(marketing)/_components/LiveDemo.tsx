"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { AgentRow } from "../../_components/run/swarm/AgentLanes";
import { CompareFrame } from "../../_components/run/swarm/ArtifactsGallery";
import SwarmPipeline from "../../_components/run/swarm/SwarmPipeline";
import { initialRunState, runReducer } from "../../_lib/runState";
import { Badge, Icon, StatusChip } from "../../_ui";
import { DEMO_EVENTS, DEMO_TOTAL_MS } from "./demoScript";

const ITEMS = ["Buy groceries", "Write the quarterly report", "Book dentist"];

/** Decorative stand-ins for the before/after screenshots: plain defaults versus the restyled app. */
function TodoBefore() {
  return (
    <div aria-hidden className="h-[250px] overflow-hidden bg-white p-3 font-serif text-black">
      <div className="text-[19px] font-bold">My Todos</div>
      <hr className="my-1 border-gray-400" />
      <div className="mt-2 flex gap-1.5">
        <span className="h-5 w-32 border border-gray-500" />
        <span className="border border-gray-500 bg-gray-200 px-1.5 text-[10px] leading-5">Add</span>
      </div>
      <ul className="mt-3 space-y-2 text-[12px]">
        {ITEMS.map((t) => (
          <li key={t} className="flex items-center gap-2">
            <span className="h-3 w-3 border border-gray-500" />
            <span className="whitespace-nowrap">{t}</span>
            <span className="ml-auto bg-gray-200 px-1 text-[9px]">del</span>
          </li>
        ))}
      </ul>
      <div className="absolute inset-y-0 right-0 w-1.5 bg-red-400" />
    </div>
  );
}
function TodoAfter() {
  return (
    <div aria-hidden className="h-full min-h-[250px] bg-[#0f121c] p-4 text-[#ebf0fa]">
      <div className="mx-auto max-w-[300px]">
        <div className="text-[22px] font-semibold tracking-tight">My todos</div>
        <div className="text-[11px] text-[#96a2b9]">3 open, 0 done</div>
        <div className="mt-3 flex items-center justify-between rounded-lg border border-[#303850] bg-[#181d2c] px-3 py-2">
          <span className="text-[11px] text-[#96a2b9]">Add a task</span>
          <span className="rounded-md bg-primary px-2.5 py-1 text-[10px] font-semibold text-[#04120c]">Add</span>
        </div>
        <ul className="mt-2.5 space-y-2">
          {ITEMS.map((t) => (
            <li key={t} className="flex items-center gap-2.5 rounded-lg border border-[#303850] bg-[#181d2c] px-3 py-2 text-[12px]">
              <span className="h-3.5 w-3.5 rounded border border-primary" />
              {t}
              <span className="ml-auto text-[10px] text-[#96a2b9]">Delete</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** The real pipeline and agent rows, driven by scripted swarm events, looping. */
export default function LiveDemo() {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const [cycle, setCycle] = useState(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const clear = () => {
      timers.current.forEach(clearTimeout);
      timers.current = [];
    };
    if (reduce) {
      // Static final frame: no animation, no loop.
      dispatch({ kind: "connecting", at: 0 });
      for (const e of DEMO_EVENTS) dispatch({ kind: "event", msg: e.msg, at: e.at });
      return clear;
    }
    dispatch({ kind: "reset" });
    dispatch({ kind: "connecting", at: performance.now() });
    for (const e of DEMO_EVENTS) timers.current.push(setTimeout(() => dispatch({ kind: "event", msg: e.msg, at: performance.now() }), e.at));
    timers.current.push(setTimeout(() => setCycle((c) => c + 1), DEMO_TOTAL_MS + 5000));
    return clear;
  }, [cycle]);

  const w = state.swarm;
  const done = state.done;
  const chip = done?.outcome === "complete" ? "complete" : state.status === "idle" ? "queued" : "running";
  const last = w.verifies[w.verifies.length - 1];
  const hasAfter = w.artifacts.some((a) => a.phase === "after");
  const agents = w.agentOrder.map((id) => w.agents[id]).slice(-6);
  const rows = w.plan?.criteria || [];

  return (
    <div
      data-testid="live-demo"
      className="overflow-hidden rounded-2xl border border-border-strong bg-panel shadow-[0_30px_80px_-30px_rgba(16,185,129,0.25),0_0_0_1px_rgba(255,255,255,0.02)]"
      role="group"
      aria-label="Animated replay of a PatchLoop swarm run on a UI task: a plan with hard and advisory checks, parallel workers, a failing check that triggers a repair, and a before and after comparison. Scripted, not a live run."
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface-container-low px-4 py-2.5">
        <span className="flex gap-1.5" aria-hidden>
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
        </span>
        <span className="ml-2 min-w-0 flex-1 truncate font-mono text-[12px] text-on-surface-variant">demo/react-todo · Improve the UI of this React app</span>
        <span className="flex items-center gap-2">
          <Badge tone="warning">scripted replay</Badge>
          <StatusChip status={chip} />
        </span>
      </div>
      <div className="grid gap-0 lg:grid-cols-[1.1fr_1fr]">
        <div className="flex min-w-0 flex-col gap-4 p-4 sm:p-5 lg:border-r lg:border-border">
          <SwarmPipeline state={state} />
          <div className="border-t border-border pt-4">
            <div className="mb-2.5 flex items-center justify-between text-[13px] font-semibold text-white">
              <span className="flex items-center gap-2">
                <Icon name="split" size={15} className="text-primary" /> Agents
              </span>
              <span className="text-[11.5px] font-normal text-on-surface-variant">{w.agentOrder.length} spawned</span>
            </div>
            <ul className="flex min-h-[318px] flex-col justify-end gap-1.5 [mask-image:linear-gradient(to_bottom,transparent,black_20px)]">
              {agents.map((a) => (
                <AgentRow key={a.id} a={a} />
              ))}
            </ul>
          </div>
        </div>
        <div className="flex min-w-0 flex-col gap-4 p-4 sm:p-5">
          <div>
            <div className="mb-2 flex items-center justify-between text-[13px] font-semibold text-white">
              <span className="flex items-center gap-2">
                <Icon name="shield-check" size={15} className="text-primary" /> Verification gates
              </span>
              {last && <span className={last.hard_pass ? "text-[12px] text-primary" : "text-[12px] text-warning"}>round {last.round}: {last.hard_pass ? "all hard gates pass" : "1 failing, repair next"}</span>}
            </div>
            <ul className="grid gap-x-3 gap-y-1 text-[12px] sm:grid-cols-2" aria-label="Criteria">
              {rows.length === 0 && <li className="text-text-subtle sm:col-span-2">Criteria appear when the planner finishes.</li>}
              {rows.map((c) => {
                const r = last?.results.find((x) => x.criterion_id === c.id);
                const st = r?.status;
                return (
                  <li key={c.id} className="flex items-center gap-1.5">
                    <Icon
                      name={st === "pass" ? "check-circle" : st === "fail" ? "x-circle" : st === "advisory" ? "info" : "clock"}
                      size={13}
                      className={st === "pass" ? "text-primary" : st === "fail" ? "text-error" : st === "advisory" ? "text-warning" : "text-text-subtle"}
                    />
                    <span className="truncate text-on-surface-variant" title={c.description}>
                      {c.kind.replace(/_/g, " ")}
                    </span>
                    <span className="sr-only">{st || "pending"}</span>
                    {!c.hard && <span className="ml-auto text-[11px] text-warning">advisory</span>}
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="min-h-0 flex-1">
            <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-white">
              <Icon name="eye" size={15} className="text-primary" /> Before and after, 375 px
            </div>
            {hasAfter ? (
              <div className="mx-auto max-w-[360px]" data-testid="demo-compare">
                <CompareFrame before={<div className="relative"><TodoBefore /></div>} after={<TodoAfter />} onFocusLabel="Drag to compare the scripted before and after screenshots" />
              </div>
            ) : (
              <div className="flex h-[250px] items-center justify-center rounded-lg border border-dashed border-border px-6 text-center text-[13px] leading-5 text-on-surface-variant">
                {w.artifacts.length > 0 ? "Before screenshot captured. The after screenshot arrives once the checks pass." : "Screenshots are captured before and after, in a headless browser."}
              </div>
            )}
          </div>
          <div className={`rounded-xl border p-3.5 transition-opacity duration-500 ${state.pr ? "border-primary/40 bg-primary/5 opacity-100" : "border-border opacity-45"}`}>
            <div className="flex items-center gap-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-primary/40 bg-primary/10 text-primary">
                <Icon name="git-pr" size={16} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-semibold text-white">{state.pr ? "Pull request #7 ready: 3 commits, one per unit" : "Opens a pull request only when hard gates pass"}</div>
                <div className="truncate font-mono text-[11.5px] text-on-surface-variant">patchloop/improve-the-ui</div>
              </div>
              <span className="shrink-0 rounded-md border border-border-strong px-2 py-1 text-[11.5px] font-semibold text-on-surface">Merge: you</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
