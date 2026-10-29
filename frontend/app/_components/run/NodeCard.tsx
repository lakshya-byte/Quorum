"use client";

import { memo } from "react";
import type { RunNode } from "../../_lib/api";
import { nodeTokens, nodeTone } from "../../_lib/runState";

const TONE = {
  green: {
    border: "border-primary/50",
    bar: "bg-primary",
    text: "text-primary",
    dot: "bg-primary",
  },
  amber: {
    border: "border-amber-400/45",
    bar: "bg-amber-400",
    text: "text-amber-300",
    dot: "bg-amber-400",
  },
  red: {
    border: "border-error/45",
    bar: "bg-error",
    text: "text-error",
    dot: "bg-error",
  },
} as const;

export function fmtMs(ms?: number | null) {
  if (ms == null || Number.isNaN(ms)) return "–";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}s`;
}

export function shortModel(m?: string | null) {
  if (!m) return null;
  return m.replace(/\s*\(.*\)$/, "").split("/").pop();
}

type Props = {
  node: RunNode;
  isBest: boolean;
  isSelected: boolean;
  lessons?: string[];
  onSelect: (id: number) => void;
};

function NodeCardImpl({ node, isBest, isSelected, lessons, onSelect }: Props) {
  const tone = nodeTone(node);
  const t = TONE[tone];
  const policyBlocked = node.policy?.ok === false;
  const securityFlagged = node.security?.ok === false;
  const flagged = policyBlocked || securityFlagged;
  const isRoot = node.parent == null;
  const pct = node.total > 0 ? Math.round((node.passed / node.total) * 100) : 0;
  const tokens = nodeTokens(node);

  return (
    <div className="flex flex-col gap-1.5 min-w-0 animate-[node-in_320ms_ease-out]">
      <button
        type="button"
        onClick={() => onSelect(node.id)}
        data-node-id={node.id}
        aria-pressed={isSelected}
        className={[
          "group relative w-full text-left rounded-xl p-3.5 transition-all duration-200 bg-surface-container-low hover:bg-surface-container",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/60",
          flagged ? `border-2 border-dashed ${policyBlocked ? "border-error/70" : "border-amber-400/70"}` : `border ${t.border}`,
          isBest ? "ring-2 ring-primary shadow-[0_0_28px_-4px_rgba(16,185,129,0.55)]" : "",
          isSelected && !isBest ? "ring-2 ring-secondary/70" : "",
        ].join(" ")}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`w-2 h-2 rounded-full shrink-0 ${t.dot}`} />
            <span className="font-mono text-[11px] text-on-surface-variant shrink-0">#{node.id}</span>
            {isRoot ? (
              <span className="text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant border border-outline-variant/60">
                original
              </span>
            ) : node.strategy ? (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-secondary/10 text-secondary border border-secondary/25 truncate">
                {node.strategy}
              </span>
            ) : null}
          </div>
          {isBest && (
            <span className="shrink-0 inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded bg-primary text-black font-semibold">
              <span className="material-symbols-outlined text-[13px]">trophy</span>
              winner
            </span>
          )}
        </div>

        <p className="mt-2 text-[13px] leading-snug text-white line-clamp-2 min-h-[2.4em]">
          {node.idea || (isRoot ? "Original buggy code" : "Candidate fix")}
        </p>

        <div className="mt-3 flex items-center gap-2">
          <div className="flex-1 h-1.5 rounded-full bg-surface-container-high overflow-hidden">
            <div className={`h-full rounded-full ${t.bar} transition-[width] duration-500`} style={{ width: `${pct}%` }} />
          </div>
          <span className={`font-mono text-[12px] font-semibold ${t.text}`}>
            {policyBlocked ? "not run" : `${node.passed}/${node.total} tests`}
          </span>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-on-surface-variant">
          {shortModel(node.model) && (
            <span className="inline-flex items-center gap-1">
              <span className="material-symbols-outlined text-[13px]">neurology</span>
              {shortModel(node.model)}
            </span>
          )}
          {node.latency_ms != null && (
            <span className="inline-flex items-center gap-1">
              <span className="material-symbols-outlined text-[13px]">timer</span>
              {fmtMs(node.latency_ms)}
            </span>
          )}
          {typeof node.score === "number" && <span>score {node.score.toFixed(3)}</span>}
          {tokens > 0 && <span>{tokens.toLocaleString()} tok</span>}
        </div>

        {(policyBlocked || securityFlagged) && (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {policyBlocked && (
              <span
                title={(node.policy?.reasons || []).join("\n")}
                className="inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded bg-error/15 text-error border border-error/40"
              >
                <span className="material-symbols-outlined text-[13px]">block</span>
                policy blocked
              </span>
            )}
            {securityFlagged && (
              <span className="inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-400/15 text-amber-300 border border-amber-400/40">
                <span className="material-symbols-outlined text-[13px]">gpp_maybe</span>
                security flagged
              </span>
            )}
          </div>
        )}
      </button>

      {lessons && lessons.length > 0 && (
        <div className="flex flex-col gap-1">
          {lessons.map((l) => (
            <div
              key={l}
              className="flex items-start gap-1.5 rounded-lg px-2.5 py-1.5 bg-secondary/5 border border-secondary/20 text-[11.5px] leading-snug text-on-surface-variant"
            >
              <span className="material-symbols-outlined text-[14px] text-secondary mt-px">psychology</span>
              <span>
                <span className="text-secondary font-medium">Critic: </span>
                {l}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const NodeCard = memo(NodeCardImpl);
export default NodeCard;
