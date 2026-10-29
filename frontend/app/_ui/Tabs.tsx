"use client";

import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "./cx";

export type TabItem<T extends string> = { id: T; label: ReactNode; badge?: ReactNode; hidden?: boolean };

export function Tabs<T extends string>({ tabs, value, onChange, label, className }: { tabs: TabItem<T>[]; value: T; onChange: (v: T) => void; label: string; className?: string }) {
  const base = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const visible = tabs.filter((t) => !t.hidden);
  const onKey = (e: KeyboardEvent) => {
    const i = visible.findIndex((t) => t.id === value);
    let n = -1;
    if (e.key === "ArrowRight") n = (i + 1) % visible.length;
    else if (e.key === "ArrowLeft") n = (i - 1 + visible.length) % visible.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = visible.length - 1;
    if (n >= 0) {
      e.preventDefault();
      onChange(visible[n].id);
      refs.current[visible[n].id]?.focus();
    }
  };
  return (
    <div role="tablist" aria-label={label} onKeyDown={onKey} className={cx("flex gap-1 overflow-x-auto border-b border-border", className)}>
      {visible.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el;
            }}
            role="tab"
            id={`${base}-${t.id}`}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            type="button"
            onClick={() => onChange(t.id)}
            className={cx(
              "focus-ring -mb-px inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2.5 text-[13px] font-medium transition-colors",
              active ? "border-primary text-white" : "border-transparent text-on-surface-variant hover:text-white"
            )}
          >
            {t.label}
            {t.badge}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div role="tabpanel" className={className}>
      {children}
    </div>
  );
}
