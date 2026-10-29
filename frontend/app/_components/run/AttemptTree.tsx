"use client";

import type { RunState } from "../../_lib/runState";
import NodeCard from "./NodeCard";
import { Icon } from "../../_ui";

type TreeProps = {
  state: RunState;
  bestId: number | null;
  selectedId: number | null;
  onSelect: (id: number) => void;
  live: boolean;
  compact?: boolean;
};

function Children({ parentId, ...p }: TreeProps & { parentId: number }) {
  const kids = p.state.children[parentId] || [];
  if (!kids.length) return null;
  const parent = p.state.nodes[parentId];
  const depth = (parent?.depth ?? 0) + 1;
  const refining = kids.filter((k) => (p.state.children[k] || []).length > 0);

  return (
    <div className="mt-3 ml-2 sm:ml-3 pl-3 sm:pl-5 border-l-2 border-outline-variant/50 flex flex-col gap-3">
      <div className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-wider text-on-surface-variant">
        <Icon name="split" size={14} className="text-secondary" />
        <span>
          Round {depth} · {kids.length} parallel {kids.length === 1 ? "attempt" : "attempts"} from #{parentId}
        </span>
      </div>
      <div className={p.compact ? "grid grid-cols-1 gap-3 sm:grid-cols-2" : "grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3"}>
        {kids.map((id) => {
          const n = p.state.nodes[id];
          return (
            <NodeCard
              key={id}
              node={n}
              isBest={p.bestId === id}
              isSelected={p.selectedId === id}
              lessons={p.state.lessons[id]}
              onSelect={p.onSelect}
            />
          );
        })}
      </div>
      {refining.map((id) => (
        <Children key={id} parentId={id} {...p} />
      ))}
    </div>
  );
}

export default function AttemptTree(p: TreeProps) {
  const roots = p.state.children[-1] || [];
  const awaitingRound = p.live && !p.state.done;

  if (!roots.length) {
    return <TreeSkeleton label={p.live ? "Testing the original code in a sandbox…" : "No attempts recorded for this run."} pulse={p.live} />;
  }

  return (
    <div className="flex flex-col gap-1" aria-live="polite">
      {roots.map((id) => (
        <div key={id}>
          <div className="max-w-md">
            <NodeCard
              node={p.state.nodes[id]}
              isBest={p.bestId === id}
              isSelected={p.selectedId === id}
              lessons={p.state.lessons[id]}
              onSelect={p.onSelect}
            />
          </div>
          <Children parentId={id} {...p} />
        </div>
      ))}
      {awaitingRound && (
        <div className="mt-3 ml-2 sm:ml-3 pl-3 sm:pl-5 border-l-2 border-dashed border-outline-variant/50">
          <div className="flex items-center gap-2 font-mono text-[11px] text-on-surface-variant py-2">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
            Agents proposing fixes in isolated sandboxes…
          </div>
          <div className={p.compact ? "grid grid-cols-1 gap-3 sm:grid-cols-2" : "grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3"}>
            <div className="h-[132px] rounded-xl bg-surface-container-low/60 border border-outline-variant/40 animate-pulse" />
            <div className="hidden sm:block h-[132px] rounded-xl bg-surface-container-low/60 border border-outline-variant/40 animate-pulse" />
          </div>
        </div>
      )}
    </div>
  );
}

export function TreeSkeleton({ label, pulse = true }: { label: string; pulse?: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="max-w-md h-[132px] rounded-xl bg-surface-container-low/60 border border-outline-variant/40 flex items-center justify-center">
        <span className={`font-mono text-[11px] text-on-surface-variant ${pulse ? "animate-pulse" : ""}`}>{label}</span>
      </div>
      <div className="ml-3 pl-5 border-l-2 border-dashed border-outline-variant/40 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        <div className={`h-[132px] rounded-xl bg-surface-container-low/40 border border-outline-variant/30 ${pulse ? "animate-pulse" : ""}`} />
        <div className={`hidden sm:block h-[132px] rounded-xl bg-surface-container-low/40 border border-outline-variant/30 ${pulse ? "animate-pulse" : ""}`} />
        <div className={`hidden xl:block h-[132px] rounded-xl bg-surface-container-low/40 border border-outline-variant/30 ${pulse ? "animate-pulse" : ""}`} />
      </div>
    </div>
  );
}
