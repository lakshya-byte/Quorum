import type { ReactNode } from "react";
import Icon, { type IconName } from "./Icon";
import { cx } from "./cx";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info";
const TONE: Record<Tone, string> = {
  neutral: "bg-surface-container-high text-on-surface-variant border-border-strong",
  success: "bg-primary/10 text-primary border-primary/35",
  warning: "bg-warning/10 text-warning border-warning/35",
  danger: "bg-error/10 text-error border-error/40",
  info: "bg-secondary/10 text-secondary border-secondary/35",
};

export function Badge({ tone = "neutral", icon, mono, className, children, title }: { tone?: Tone; icon?: IconName; mono?: boolean; className?: string; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cx("inline-flex items-center gap-1 rounded-md border px-1.5 h-5 text-[11px] font-medium leading-none whitespace-nowrap", mono && "font-mono", TONE[tone], className)}
    >
      {icon && <Icon name={icon} size={12} />}
      {children}
    </span>
  );
}

export type RunStatus = "running" | "solved" | "unsolved" | "failed" | "blocked" | "queued" | "complete" | "partial" | "needs_input";
const STATUS: Record<RunStatus, { tone: Tone; label: string; icon: IconName; pulse?: boolean }> = {
  running: { tone: "info", label: "Running", icon: "loader", pulse: true },
  queued: { tone: "neutral", label: "Queued", icon: "clock" },
  solved: { tone: "success", label: "Solved", icon: "check-circle" },
  unsolved: { tone: "warning", label: "Unsolved", icon: "alert" },
  failed: { tone: "danger", label: "Failed", icon: "x-circle" },
  blocked: { tone: "danger", label: "Blocked", icon: "ban" },
  complete: { tone: "success", label: "Complete", icon: "check-circle" },
  partial: { tone: "warning", label: "Partial", icon: "alert" },
  needs_input: { tone: "info", label: "Needs input", icon: "info" },
};

export function StatusChip({ status, label, className }: { status: RunStatus; label?: string; className?: string }) {
  const s = STATUS[status];
  return (
    <span
      data-status={status}
      className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 h-6 text-[12px] font-medium leading-none whitespace-nowrap", TONE[s.tone], className)}
    >
      {s.pulse ? (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      ) : (
        <Icon name={s.icon} size={13} />
      )}
      {label ?? s.label}
    </span>
  );
}
