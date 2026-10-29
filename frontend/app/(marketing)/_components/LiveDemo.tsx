"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import AttemptTree from "../../_components/run/AttemptTree";
import DiffViewer from "../../_components/run/DiffViewer";
import Pipeline from "../../_components/run/Pipeline";
import { initialRunState, runReducer } from "../../_lib/runState";
import { parseUnifiedDiff } from "../../_lib/unified";
import { Badge, Icon, StatusChip } from "../../_ui";
import { DEMO_DIFF, DEMO_EVENTS, DEMO_TOTAL_MS } from "./demoScript";

const noop = () => {};
const DIFF_FILES = parseUnifiedDiff(DEMO_DIFF);

/** The real attempt tree + pipeline, driven by scripted events, looping. */
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
      // Static final frame: no animation.
      dispatch({ kind: "connecting", at: 0 });
      for (const e of DEMO_EVENTS) dispatch({ kind: "event", msg: e.msg, at: e.at });
      return clear;
    }
    dispatch({ kind: "reset" });
    dispatch({ kind: "connecting", at: performance.now() });
    for (const e of DEMO_EVENTS) timers.current.push(setTimeout(() => dispatch({ kind: "event", msg: e.msg, at: performance.now() }), e.at));
    timers.current.push(setTimeout(() => setCycle((c) => c + 1), DEMO_TOTAL_MS + 4500));
    return clear;
  }, [cycle]);

  const done = state.done;
  const chip = done?.solved ? "solved" : state.status === "idle" ? "queued" : "running";
  const ready = !!state.pr;

  return (
    <div
      className="overflow-hidden rounded-2xl border border-border-strong bg-panel shadow-[0_30px_80px_-30px_rgba(16,185,129,0.25),0_0_0_1px_rgba(255,255,255,0.02)]"
      role="img"
      aria-label="Animated replay of a PatchLoop run: the agent team locates the bug, tries several fixes in parallel, and opens a pull request."
    >
      <div className="flex items-center gap-2 border-b border-border bg-surface-container-low px-4 py-2.5">
        <span className="flex gap-1.5" aria-hidden>
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
        </span>
        <span className="ml-2 truncate font-mono text-[12px] text-on-surface-variant">
          demo/inventory-api · reserving the last unit fails
        </span>
        <span className="ml-auto flex items-center gap-2">
          <Badge tone="warning">scripted replay</Badge>
          <StatusChip status={chip} />
        </span>
      </div>
      <div className="grid h-[560px] gap-0 lg:h-[640px] lg:grid-cols-[1.15fr_1fr]">
        <div className="flex flex-col gap-5 overflow-hidden p-4 sm:p-5 lg:border-r lg:border-border">
          <Pipeline state={state} />
          <div className="flex min-h-0 flex-1 flex-col border-t border-border pt-4">
            <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-white">
              <Icon name="split" size={15} className="text-primary" /> Attempts
            </div>
            <div className="flex min-h-0 flex-1 flex-col justify-end overflow-hidden [mask-image:linear-gradient(to_bottom,transparent,black_28px)]">
              <AttemptTree state={state} bestId={done?.solved ? done.best : null} selectedId={null} onSelect={noop} live={!done} compact />
            </div>
          </div>
        </div>
        <div className="hidden flex-col gap-4 overflow-hidden p-5 lg:flex" aria-hidden={!ready && !done}>
          {done ? (
            <>
              <div className="flex items-center gap-2 text-[13px] font-semibold text-white">
                <Icon name="diff" size={15} className="text-primary" /> Winning patch, two files
              </div>
              <div className="min-h-0 flex-1 overflow-hidden">
                <DiffViewer files={DIFF_FILES} />
              </div>
              <div
                className={`rounded-xl border p-4 transition-opacity duration-500 ${ready ? "border-primary/40 bg-primary/5 opacity-100" : "border-border opacity-40"}`}
              >
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-primary/40 bg-primary/10 text-primary">
                    <Icon name="git-pr" size={18} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[14px] font-semibold text-white">{ready ? "Pull request #42 ready for review" : "Opening pull request"}</div>
                    <div className="truncate font-mono text-[12px] text-on-surface-variant">patchloop/reserve-last-unit</div>
                  </div>
                  <span className="rounded-md border border-border-strong px-2.5 py-1.5 text-[12px] font-semibold text-on-surface">Merge: you</span>
                </div>
              </div>
            </>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-on-surface-variant">
              <Icon name="code" size={22} className="text-text-subtle" />
              <p className="max-w-[240px] text-[13px] leading-5">The winning patch and pull request appear here when a candidate passes every test.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
