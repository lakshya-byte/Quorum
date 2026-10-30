"use client";

import type { RunState } from "../../../_lib/runState";
import { fmtSecs, fmtTokens } from "../../../_lib/swarm";
import { cx } from "../../../_ui";
import { totalTokens } from "../../../_lib/runState";

function Meter({ label, value, max, text, id }: { label: string; value: number; max: number; text: string; id: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const hot = pct >= 85;
  return (
    <div className="min-w-0 flex-1" data-testid={`meter-${id}`}>
      <div className="mb-1.5 flex items-baseline justify-between gap-2 text-[12px]">
        <span id={`meter-${id}-l`} className="text-on-surface-variant">
          {label}
        </span>
        <span className="tabular-nums text-white">{text}</span>
      </div>
      <div role="progressbar" aria-labelledby={`meter-${id}-l`} aria-valuemin={0} aria-valuemax={max} aria-valuenow={Math.min(value, max)} aria-valuetext={text} className="h-1.5 overflow-hidden rounded-full bg-surface-container-high">
        <div className={cx("h-full rounded-full transition-[width] duration-500", hot ? "bg-warning" : "bg-primary")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** Budget: tokens, wall clock and workers against the caps the scheduler enforces. */
export default function BudgetMeter({ state }: { state: RunState }) {
  const b = state.swarm.budget;
  const lim = state.swarm.plan?.swarm?.limits;
  const done = state.done;
  const tokens = done ? totalTokens(state) : (b?.tokens_used ?? state.tokens);
  const tokenMax = b?.tokens_limit ?? lim?.max_tokens ?? 0;
  const wall = done?.latency_ms != null ? done.latency_ms / 1000 : (b?.wall_s ?? 0);
  const wallMax = b?.wall_limit_s ?? lim?.max_wall_s ?? 0;
  const active = done ? 0 : (b?.workers_active ?? 0);
  const workerMax = state.swarm.plan?.swarm?.max_parallel ?? lim?.max_workers ?? 0;
  if (!b && !done && !state.swarm.plan) return null;
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:gap-6" aria-label="Budget" role="group" data-testid="budget">
      <Meter id="tokens" label="Tokens" value={tokens} max={tokenMax} text={tokenMax ? `${fmtTokens(tokens)} / ${fmtTokens(tokenMax)}` : fmtTokens(tokens)} />
      <Meter id="wall" label="Wall time" value={wall} max={wallMax} text={wallMax ? `${fmtSecs(wall)} / ${fmtSecs(wallMax)}` : fmtSecs(wall)} />
      <Meter id="workers" label="Workers running" value={active} max={workerMax} text={workerMax ? `${active} / ${workerMax}` : String(active)} />
    </div>
  );
}
