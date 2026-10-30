"use client";

import { useEffect, useState, type ReactNode } from "react";

export function LiveTimer({ startedAt, endedAt, finalMs }: { startedAt: number | null; endedAt: number | null; finalMs?: number }) {
  const [now, setNow] = useState(() => (typeof performance !== "undefined" ? performance.now() : 0));
  const running = startedAt != null && endedAt == null && finalMs == null;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(performance.now()), 200);
    return () => clearInterval(t);
  }, [running]);
  let ms: number | null = null;
  if (finalMs != null) ms = finalMs;
  else if (startedAt != null) ms = (endedAt ?? now) - startedAt;
  return <span className="tabular-nums">{ms == null ? "–" : `${(Math.max(0, ms) / 1000).toFixed(1)}s`}</span>;
}

export function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-[11.5px] text-on-surface-variant">{label}</span>
      <span className="text-[15px] font-semibold tabular-nums text-white">{children}</span>
    </div>
  );
}

