"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { githubApi, runsApi, type RepoSummary, type Run } from "../../_lib/api";
import { Icon, cx, type IconName } from "../../_ui";

type Item = { id: string; label: string; hint?: string; icon: IconName; href: string; group: string };

const PAGES: Item[] = [
  { id: "p-dash", label: "Dashboard", icon: "home", href: "/dashboard", group: "Go to" },
  { id: "p-new", label: "New task", icon: "bug", href: "/new", group: "Go to" },
  { id: "p-int", label: "Integrations", icon: "plug", href: "/integrations", group: "Go to" },
  { id: "p-tok", label: "API tokens", icon: "key", href: "/settings/tokens", group: "Go to" },
  { id: "p-try", label: "Live demo", icon: "play", href: "/try", group: "Go to" },
  { id: "p-docs", label: "Docs", icon: "book", href: "/docs", group: "Go to" },
];

/** Cmd/Ctrl+K: jump to a page, a repository (starts /new with it) or a recent run. */
export default function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [runs, setRuns] = useState<Run[]>([]);
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") setOpen(false);
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("patchloop:palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("patchloop:palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the palette each time it opens
    setQ("");
    setSel(0);
    setTimeout(() => inputRef.current?.focus(), 0);
    runsApi.list().then((r) => setRuns((r || []).slice(0, 8))).catch(() => {});
    githubApi.repos("").then((r) => setRepos(r || [])).catch(() => {});
  }, [open]);

  const items = useMemo(() => {
    const all: Item[] = [
      ...PAGES,
      ...repos.map((r): Item => ({ id: "r-" + r.fullName, label: r.fullName, hint: "repository", icon: "github", href: "/new", group: "Repositories" })),
      ...runs.map((r): Item => ({ id: "u-" + r.id, label: r.task || r.bugId || r.id, hint: r.repo || "demo bug", icon: "git-pr", href: `/runs/${r.id}`, group: "Recent runs" })),
    ];
    const s = q.trim().toLowerCase();
    return s ? all.filter((i) => (i.label + " " + (i.hint || "")).toLowerCase().includes(s)) : all;
  }, [q, runs, repos]);

  if (!open) return null;
  const go = (i?: Item) => {
    if (!i) return;
    setOpen(false);
    router.push(i.href);
  };

  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center px-4 pt-[14vh]" role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
      <div className="relative w-full max-w-lg overflow-hidden rounded-xl border border-border-strong bg-surface-container shadow-pop">
        <div className="flex items-center gap-2 border-b border-border px-4">
          <Icon name="search" size={16} className="text-text-subtle" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setSel(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") (e.preventDefault(), setSel((s) => Math.min(items.length - 1, s + 1)));
              else if (e.key === "ArrowUp") (e.preventDefault(), setSel((s) => Math.max(0, s - 1)));
              else if (e.key === "Enter") go(items[sel]);
            }}
            placeholder="Jump to a page, repository or run"
            aria-label="Search"
            className="h-12 flex-1 bg-transparent text-[14px] text-white placeholder:text-text-subtle focus:outline-none"
          />
          <kbd className="rounded border border-border-strong px-1.5 py-0.5 font-mono text-[11px] text-text-subtle">esc</kbd>
        </div>
        <ul className="max-h-[50vh] overflow-auto py-1" role="listbox">
          {items.length === 0 && <li className="px-4 py-6 text-center text-[13px] text-on-surface-variant">Nothing matches.</li>}
          {items.map((it, i) => (
            <li key={it.id} role="option" aria-selected={i === sel}>
              {(i === 0 || items[i - 1].group !== it.group) && <div className="px-4 pb-1 pt-2.5 text-[11px] font-medium uppercase tracking-wider text-text-subtle">{it.group}</div>}
              <button
                type="button"
                onMouseEnter={() => setSel(i)}
                onClick={() => go(it)}
                className={cx("flex w-full items-center gap-3 px-4 py-2 text-left text-[13.5px]", i === sel ? "bg-primary/10 text-white" : "text-on-surface")}
              >
                <Icon name={it.icon} size={15} className={i === sel ? "text-primary" : "text-text-subtle"} />
                <span className="min-w-0 flex-1 truncate">{it.label}</span>
                {it.hint && <span className="shrink-0 font-mono text-[11.5px] text-text-subtle">{it.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
