"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { notificationsApi, type Notification } from "../../_lib/api";
import { Icon, cx } from "../../_ui";

export default function NotificationsBell() {
  const [items, setItems] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setItems((await notificationsApi.list()) || []);
    } catch {
      // the bell is optional; stay quiet if the endpoint is unavailable
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const unread = items.filter((n) => !n.read).length;
  const markRead = async (n: Notification) => {
    setItems((l) => l.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
    try {
      await notificationsApi.read(n.id);
    } catch {
      // ignore
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          if (!open) load();
        }}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        aria-haspopup="true"
        data-testid="bell"
        className="focus-ring relative flex h-9 w-9 items-center justify-center rounded-lg border border-border-strong text-on-surface-variant hover:text-white"
      >
        <Icon name="bell" size={17} />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-[#04120c]">{unread}</span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-[min(360px,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border-strong bg-surface-container shadow-pop">
          <div className="border-b border-border px-4 py-2.5 text-[13px] font-semibold text-white">Notifications</div>
          {items.length === 0 ? (
            <p className="px-4 py-8 text-center text-[13px] text-on-surface-variant">Nothing yet. You will see a note here when a pull request is opened, merged, or a run fails.</p>
          ) : (
            <ul className="max-h-80 overflow-auto">
              {items.map((n) => (
                <li key={n.id} className="border-b border-border/60 last:border-0">
                  <Link
                    href={n.runId ? `/runs/${n.runId}` : "/dashboard"}
                    onClick={() => {
                      markRead(n);
                      setOpen(false);
                    }}
                    className="focus-ring flex gap-2.5 px-4 py-3 hover:bg-surface-container-high"
                  >
                    <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", n.read ? "bg-border-strong" : "bg-primary")} />
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-white">{n.title}</span>
                      {n.body && <span className="block truncate text-[12.5px] text-on-surface-variant">{n.body}</span>}
                      <span className="block text-[11.5px] text-text-subtle">{new Date(n.createdAt).toLocaleString()}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
