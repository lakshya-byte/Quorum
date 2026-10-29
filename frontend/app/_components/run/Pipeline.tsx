"use client";

import { pipelineStages, type RunState, type StageId, type StageState } from "../../_lib/runState";
import { Icon, cx, type IconName } from "../../_ui";

const STAGE_ICON: Record<StageId, IconName> = {
  repo: "folder",
  locate: "crosshair",
  repro: "bug",
  propose: "sparkles",
  test: "flask",
  critic: "scale",
  review: "eye",
  pr: "git-pr",
};

const STATE_LABEL: Record<StageState, string> = { pending: "waiting", active: "in progress", done: "done", skipped: "skipped", warn: "needs attention" };

export default function Pipeline({ state }: { state: RunState }) {
  const stages = pipelineStages(state);
  return (
    <ol className="grid grid-cols-4 gap-x-1 gap-y-4 sm:grid-cols-8" aria-label="Run pipeline" data-testid="pipeline">
      {stages.map((s, i) => (
        <li key={s.id} data-stage={s.id} data-state={s.state} className="relative flex min-w-0 flex-col items-center gap-1.5 text-center">
          {i < stages.length - 1 && (
            <span
              aria-hidden
              className={cx(
                "absolute left-[calc(50%+18px)] right-[calc(-50%+18px)] top-[17px] hidden h-px sm:block",
                s.state === "done" ? "bg-primary/60" : s.state === "active" ? "flow-line bg-transparent [background:repeating-linear-gradient(90deg,var(--primary)_0_4px,transparent_4px_8px)]" : "bg-border-strong"
              )}
            />
          )}
          <span
            className={cx(
              "relative z-10 flex h-[34px] w-[34px] items-center justify-center rounded-full border transition-colors",
              s.state === "done" && "border-primary/60 bg-primary/15 text-primary",
              s.state === "active" && "border-secondary bg-secondary/10 text-secondary shadow-[0_0_0_4px_rgba(6,182,212,0.12)]",
              s.state === "warn" && "border-warning/60 bg-warning/10 text-warning",
              s.state === "pending" && "border-border-strong bg-bg text-text-subtle",
              s.state === "skipped" && "border-border bg-bg text-text-subtle opacity-60"
            )}
          >
            {s.state === "done" ? <Icon name="check" size={16} strokeWidth={2.5} /> : <Icon name={STAGE_ICON[s.id]} size={16} className={s.state === "active" ? "animate-pulse" : ""} />}
          </span>
          <span className={cx("text-[12px] font-medium", s.state === "pending" || s.state === "skipped" ? "text-text-subtle" : "text-white")}>{s.label}</span>
          <span className="sr-only">{STATE_LABEL[s.state]}</span>
          <span className="hidden min-h-4 max-w-full truncate text-[11px] text-on-surface-variant sm:block" title={s.detail || s.hint}>
            {s.detail || (s.state === "active" ? s.hint : "")}
          </span>
        </li>
      ))}
    </ol>
  );
}
