"use client";

import type { Bug } from "../../_lib/api";

const TIER_ORDER = ["easy", "medium", "hard"];

export function groupByTier(bugs: Bug[]): [string, Bug[]][] {
  const groups = new Map<string, Bug[]>();
  for (const b of bugs) {
    const t = b.tier || "other";
    if (!groups.has(t)) groups.set(t, []);
    groups.get(t)!.push(b);
  }
  return [...groups.entries()].sort((a, b) => {
    const ia = TIER_ORDER.indexOf(a[0]);
    const ib = TIER_ORDER.indexOf(b[0]);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a[0].localeCompare(b[0]);
  });
}

const TIER_CLS: Record<string, string> = {
  easy: "text-primary border-primary/30",
  medium: "text-secondary border-secondary/30",
  hard: "text-amber-300 border-amber-400/30",
};

export default function BugPicker({
  bugs,
  selected,
  onSelect,
}: {
  bugs: Bug[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="flex flex-col gap-4" role="radiogroup" aria-label="Choose a bug">
      {groupByTier(bugs).map(([tier, list]) => (
        <div key={tier} className="flex flex-col gap-2">
          <div className="font-mono text-[10.5px] uppercase tracking-wider text-on-surface-variant">{tier}</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
            {list.map((b) => {
              const active = selected === b.id;
              return (
                <button
                  key={b.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  data-bug-id={b.id}
                  onClick={() => onSelect(b.id)}
                  className={`text-left rounded-xl border p-3.5 transition-all ${
                    active
                      ? "border-primary/70 bg-primary/5 ring-1 ring-primary/40"
                      : "border-outline-variant/60 bg-surface-container-low hover:border-outline hover:bg-surface-container"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-mono text-[13px] text-white leading-snug">{b.title}</span>
                    <span className={`shrink-0 text-[9.5px] font-mono uppercase px-1.5 py-0.5 rounded border ${TIER_CLS[tier] || "text-on-surface-variant border-outline-variant/60"}`}>
                      {tier}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[12px] leading-snug text-on-surface-variant line-clamp-2">{b.issue}</p>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
