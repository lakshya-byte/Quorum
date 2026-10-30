"use client";

import { useState } from "react";
import type { RunState } from "../../../_lib/runState";
import { parseUnifiedDiff } from "../../../_lib/unified";
import { Badge, Card, Icon, TabPanel, Tabs } from "../../../_ui";
import DiffViewer from "../DiffViewer";

/** Combined diff (the commit-per-unit branch squashed for reading) plus one tab per unit. */
export default function DiffPanel({ state }: { state: RunState }) {
  const w = state.swarm;
  const bestId = state.done?.best ?? null;
  const best = bestId != null ? state.nodes[bestId] : undefined;
  const unitDiffs = Object.values(w.units).filter((u) => u.diff);
  const combined = best?.diff || unitDiffs.map((u) => u.diff).join("");
  const [tab, setTab] = useState("combined");
  const tabs = [
    { id: "combined", label: "Combined", hidden: !combined },
    ...unitDiffs.map((u) => ({ id: u.id, label: `Unit ${u.id}`, hidden: false, badge: u.status === "merged" || u.status === "passed" ? undefined : <Badge tone="neutral">{u.status}</Badge> })),
  ];
  if (!combined && unitDiffs.length === 0) return null;
  const sel = tabs.some((t) => t.id === tab && !t.hidden) ? tab : tabs.find((t) => !t.hidden)?.id || "combined";
  const text = sel === "combined" ? combined : w.units[sel]?.diff || "";
  const files = parseUnifiedDiff(text);
  const title = sel === "combined" ? w.plan?.units.map((u) => u.title).join("; ") : w.plan?.units.find((u) => u.id === sel)?.title;
  return (
    <section aria-labelledby="diff-h" className="flex flex-col gap-3" data-testid="diff-panel">
      <h2 id="diff-h" className="flex items-center gap-2 text-[15px] font-semibold text-white">
        <Icon name="diff" size={16} className="text-primary" />
        Changes
        <span className="text-[12px] font-normal text-on-surface-variant">the pull request has one commit per unit</span>
      </h2>
      <Card className="flex flex-col gap-3 p-4">
        <Tabs label="Diff scope" value={sel} onChange={setTab} tabs={tabs} />
        <TabPanel>
          <DiffViewer files={files} caption={title} />
        </TabPanel>
      </Card>
    </section>
  );
}
