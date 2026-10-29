import type { HTMLAttributes, ReactNode } from "react";
import { cx } from "./cx";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("rounded-xl border border-border bg-panel shadow-card", className)} {...rest} />;
}

export function CardHeader({ title, description, action, className }: { title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex items-start justify-between gap-3 px-5 pt-4 pb-3", className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold text-white leading-6">{title}</h2>
        {description && <p className="mt-0.5 text-[13px] leading-5 text-on-surface-variant">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("px-5 pb-5", className)} {...rest} />;
}

export function PageHeader({ title, description, actions, eyebrow }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-[12px] font-medium text-primary">{eyebrow}</div>}
        <h1 className="text-[26px] sm:text-[30px] leading-tight font-semibold tracking-tight text-white">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-[14px] leading-6 text-on-surface-variant">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
