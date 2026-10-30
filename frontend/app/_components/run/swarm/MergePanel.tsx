"use client";

import type { RunState } from "../../../_lib/runState";
import { Badge, Card, Icon, type Tone } from "../../../_ui";

const TONE: Record<string, { tone: Tone; label: string; text: string }> = {
  ok: { tone: "success", label: "merged cleanly", text: "No overlapping edits." },
  conflict: { tone: "warning", label: "conflict", text: "Overlapping edits found. The integrator agent takes over." },
  resolved: { tone: "success", label: "conflict resolved", text: "The integrator merged the overlapping edits; the build and tests run again at verification." },
  failed: { tone: "danger", label: "merge failed", text: "The units could not be combined." },
};

/** Integrator merges unit diffs on a fresh fork; real conflicts are handed to the integrator agent. */
export default function MergePanel({ state }: { state: RunState }) {
  const merges = state.swarm.merges;
  if (merges.length === 0) return null;
  return (
    <Card className="p-5" data-testid="merge-panel">
      <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-white">
        <Icon name="git-branch" size={16} className="text-primary" />
        Merge
      </h2>
      <ol className="flex flex-col gap-2">
        {merges.map((m, i) => {
          const t = TONE[m.status] || TONE.ok;
          return (
            <li key={i} data-merge={m.status} className="flex flex-col gap-1 rounded-lg border border-border bg-surface-container-low px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={t.tone}>{t.label}</Badge>
                <span className="font-mono text-[12px] text-on-surface-variant">units {m.units.join(", ")}</span>
              </div>
              <p className="text-[12.5px] leading-5 text-on-surface-variant">{t.text}</p>
              {m.conflicts.length > 0 && <p className="font-mono text-[11.5px] text-warning [overflow-wrap:anywhere]">conflict in: {m.conflicts.join(", ")}</p>}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
