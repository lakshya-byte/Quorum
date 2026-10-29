"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import Icon from "./Icon";
import { cx } from "./cx";

type ToastTone = "success" | "error" | "info";
type ToastItem = { id: number; tone: ToastTone; message: string };
type Ctx = { toast: (message: string, tone?: ToastTone) => void };

const ToastContext = createContext<Ctx>({ toast: () => {} });
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const toast = useCallback(
    (message: string, tone: ToastTone = "info") => {
      const id = next.current++;
      setItems((l) => [...l.slice(-3), { id, tone, message }]);
      setTimeout(() => dismiss(id), tone === "error" ? 7000 : 4500);
    },
    [dismiss]
  );
  const value = useMemo(() => ({ toast }), [toast]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[80] flex flex-col items-center gap-2 p-4 sm:items-end" role="region" aria-label="Notifications">
        {items.map((t) => (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className={cx(
              "pointer-events-auto flex w-full max-w-sm animate-[toast-in_200ms_ease-out] items-start gap-2.5 rounded-lg border bg-surface-container px-3.5 py-3 text-[13.5px] shadow-pop",
              t.tone === "success" && "border-primary/40",
              t.tone === "error" && "border-error/50",
              t.tone === "info" && "border-border-strong"
            )}
          >
            <Icon
              name={t.tone === "success" ? "check-circle" : t.tone === "error" ? "alert" : "info"}
              size={18}
              className={cx("mt-px", t.tone === "success" && "text-primary", t.tone === "error" && "text-error", t.tone === "info" && "text-secondary")}
            />
            <span className="flex-1 leading-5 text-on-surface">{t.message}</span>
            <button type="button" onClick={() => dismiss(t.id)} className="focus-ring rounded text-on-surface-variant hover:text-white" aria-label="Dismiss">
              <Icon name="x" size={16} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
