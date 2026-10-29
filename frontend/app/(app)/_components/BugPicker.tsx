"use client";

import type { Bug } from "../../_lib/api";
import { Badge, cx, type Tone } from "../../_ui";

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

const TIER_TONE: Record<string, Tone> = { easy: "success", medium: "info", hard: "warning" };

export default function BugPicker({ bugs, selected, onSelect }: { bugs: Bug[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="flex flex-col gap-5" role="radiogroup" aria-label="Choose a bug">
      {groupByTier(bugs).map(([tier, list]) => (
        <div key={tier} className="flex flex-col gap-2.5">
          <div className="text-[12px] font-medium capitalize text-on-surface-variant">{tier}</div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
                  className={cx(
                    "focus-ring rounded-xl border p-4 text-left transition-colors",
                    active ? "border-primary/60 bg-primary/5" : "border-border bg-surface-container-low hover:border-border-strong hover:bg-surface-container"
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[14px] font-medium leading-snug text-white">{b.title}</span>
                    <Badge tone={TIER_TONE[tier] || "neutral"}>{tier}</Badge>
                  </div>
                  <p className="mt-1.5 line-clamp-2 text-[13px] leading-5 text-on-surface-variant">{b.issue}</p>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
