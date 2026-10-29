"use client";

import { useState } from "react";
import Link from "next/link";

const METHODS = [
  {
    id: "cli",
    label: "CLI",
    command: "patchloop login --token plk_...  &&  patchloop fix paginate",
    note: "Create a token under Settings → API tokens, then run a fix from your terminal.",
  },
  {
    id: "api",
    label: "HTTP API",
    command:
      'curl -X POST http://localhost:8080/api/runs -H "Authorization: Bearer plk_..." -H "Content-Type: application/json" -d \'{"bugId":"paginate"}\'',
    note: "Then stream GET /api/runs/:id/events (server-sent events).",
  },
  {
    id: "local",
    label: "Run locally",
    command: "cd frontend && npm ci && npm run dev",
    note: "Frontend on :3000, Go backend on :8080, Python agent on :8001 (internal). See Getting started.",
  },
  {
    id: "mock",
    label: "Frontend only",
    command: "cd frontend && npm run mock & NEXT_PUBLIC_API_URL=http://localhost:8080 npm run dev",
    note: "A dependency-free mock backend that streams scripted runs. Any OTP is 123456.",
  },
];

export default function Quickstart() {
  const [activeId, setActiveId] = useState(METHODS[0].id);
  const [copied, setCopied] = useState(false);

  const active = METHODS.find((m) => m.id === activeId)!;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(active.command);
      setCopied(true);
    } catch {
      setCopied(false);
    }
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section id="quickstart" className="w-full max-w-5xl mx-auto px-4 lg:px-8 py-20 lg:py-24 scroll-mt-14">
      <div className="rounded-2xl bg-surface-container-low border border-outline-variant/70 p-6 sm:p-10 shadow-2xl relative overflow-hidden">
        <div
          aria-hidden
          className="absolute -bottom-24 left-1/2 -translate-x-1/2 w-96 h-48 bg-primary/10 blur-[90px] pointer-events-none rounded-full"
        />

        <div className="text-center max-w-xl mx-auto">
          <span className="font-mono text-[11px] uppercase tracking-wider text-primary">QUICKSTART</span>
          <h2 className="mt-2 text-2xl lg:text-3xl text-white font-semibold tracking-tight">Fix a bug from the web, the CLI or the API</h2>
          <p className="mt-2 text-on-surface-variant text-[13px]">
            The demo bugs are small Python functions with unittest suites. Start with the
            live demo, no account needed.
          </p>
        </div>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-2 border-b border-outline-variant/40 pb-3">
          {METHODS.map((method) => (
            <button
              key={method.id}
              onClick={() => setActiveId(method.id)}
              className={`px-3 py-1 rounded font-mono text-[12px] transition-colors ${
                activeId === method.id
                  ? "text-primary bg-primary/10 border border-primary/30 font-medium"
                  : "text-on-surface-variant hover:text-white border border-transparent"
              }`}
            >
              {method.label}
            </button>
          ))}
        </div>

        <div className="w-full max-w-2xl mx-auto mt-6 p-3.5 rounded-lg bg-[#07090e] border border-outline-variant/60 flex items-center justify-between shadow-inner gap-3">
          <div className="flex items-center gap-2.5 overflow-x-auto font-mono text-[13px] text-white px-2">
            <span className="text-primary select-none font-semibold">$</span>
            <span className="text-secondary select-all whitespace-nowrap">{active.command}</span>
          </div>
          <button
            onClick={copy}
            className="shrink-0 px-3 py-1.5 rounded bg-surface-container border border-outline-variant/50 text-on-surface-variant hover:text-white hover:bg-surface-bright transition-colors flex items-center gap-1.5 font-mono text-[11px]"
          >
            <span className="material-symbols-outlined text-[15px]">{copied ? "check" : "content_copy"}</span>
            <span className={copied ? "text-primary" : undefined}>{copied ? "Copied!" : "Copy"}</span>
          </button>
        </div>
        <p className="mt-3 text-center text-[12px] text-on-surface-variant">{active.note}</p>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            href="/try"
            className="group relative inline-flex items-center justify-center gap-2 px-8 py-3 rounded-lg bg-primary text-black text-[14px] font-semibold shadow-[0_0_24px_rgba(16,185,129,0.35)] hover:bg-[#34d399] transition-all duration-200"
          >
            <span className="material-symbols-outlined text-[18px]">play_arrow</span>
            <span>Try the live demo</span>
            <span className="material-symbols-outlined text-[16px] transition-transform duration-200 group-hover:translate-x-1">arrow_forward</span>
          </Link>
          <Link href="/docs/getting-started" className="text-[13px] text-on-surface-variant hover:text-white">
            Read the docs →
          </Link>
        </div>
      </div>
    </section>
  );
}
