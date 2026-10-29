import type { ReactNode } from "react";
import Icon, { type IconName } from "./Icon";

export function EmptyState({ icon = "layers", title, description, action }: { icon?: IconName; title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-border-strong bg-surface-container-low text-on-surface-variant">
        <Icon name={icon} size={20} />
      </div>
      <h3 className="mt-4 text-[15px] font-semibold text-white">{title}</h3>
      {description && <p className="mt-1.5 max-w-sm text-[13.5px] leading-6 text-on-surface-variant">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorNote({ children, tone = "error", className = "" }: { children: ReactNode; tone?: "error" | "warning" | "info"; className?: string }) {
  const cls =
    tone === "error"
      ? "border-error/40 bg-error/5 text-error"
      : tone === "warning"
        ? "border-warning/40 bg-warning/5 text-warning"
        : "border-secondary/35 bg-secondary/5 text-secondary";
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`flex items-start gap-2 rounded-lg border px-3.5 py-2.5 text-[13.5px] leading-5 ${cls} ${className}`}>
      <Icon name={tone === "info" ? "info" : "alert"} size={16} className="mt-0.5" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
