"use client";

import { useState } from "react";
import Link from "next/link";

type Line = { n: number; text: string; kind?: "add" | "del" };

const BEFORE: Line[] = [
  { n: 1, text: "def paginate(items, page, per_page):" },
  { n: 2, text: '    """Return the items on the given 1-indexed page."""' },
  { n: 3, text: "    start = page * per_page", kind: "del" },
  { n: 4, text: "    return items[start:start + per_page]" },
];

const AFTER: Line[] = [
  { n: 1, text: "def paginate(items, page, per_page):" },
  { n: 2, text: '    """Return the items on the given 1-indexed page."""' },
  { n: 3, text: "    if page < 1:", kind: "add" },
  { n: 4, text: '        raise ValueError("page must be >= 1")', kind: "add" },
  { n: 5, text: "    start = (page - 1) * per_page", kind: "add" },
  { n: 6, text: "    return items[start:start + per_page]" },
];

function Code({ lines }: { lines: Line[] }) {
  return (
    <div className="flex flex-col text-on-surface-variant font-mono text-[13px] [font-variant-ligatures:none]">
      {lines.map((l) => (
        <div
          key={l.n + l.text}
          className={`flex items-center gap-4 py-0.5 px-2 whitespace-pre ${
            l.kind === "del" ? "bg-error/15 text-error font-medium" : l.kind === "add" ? "bg-primary/15 text-primary font-medium" : ""
          }`}
        >
          <span className="w-8 text-outline text-right select-none">{l.n}</span>
          <span>
            {l.kind === "del" ? "- " : l.kind === "add" ? "+ " : "  "}
            {l.text}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function ProofExplorer() {
  const [unified, setUnified] = useState(false);

  return (
    <section
      id="proof-explorer"
      className="w-full bg-[#090c12] border-y border-outline-variant/50 py-20 lg:py-28 scroll-mt-14"
    >
      <div className="max-w-7xl mx-auto px-4 lg:px-8">
        <div className="flex flex-col md:flex-row md:items-end justify-between mb-8 gap-4">
          <div>
            <div className="font-mono text-[11px] uppercase tracking-wider text-primary">BEFORE AND AFTER</div>
            <h2 className="mt-2 text-2xl lg:text-3xl text-white font-semibold tracking-tight">The proof is the test run</h2>
            <p className="mt-2 text-on-surface-variant text-[13px] max-w-lg">
              The same tests run against the original code and against the winning patch,
              each inside an isolated Nebius Sandbox. Example from the paginate demo bug.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setUnified((v) => !v)}
              className="px-3.5 py-1.5 rounded-lg bg-surface-container border border-outline-variant/60 text-white font-mono text-[12px] hover:bg-surface-bright transition-colors flex items-center gap-1.5"
            >
              <span className="material-symbols-outlined text-[15px]">splitscreen</span>
              <span>Layout: {unified ? "Stacked" : "Side-by-side"}</span>
            </button>
            <Link
              href="/try"
              className="px-3.5 py-1.5 rounded-lg bg-primary/10 border border-primary/30 text-primary font-mono text-[12px] hover:bg-primary/20 transition-colors flex items-center gap-1.5"
            >
              <span className="material-symbols-outlined text-[15px]">play_arrow</span>
              <span>Run it yourself</span>
            </Link>
          </div>
        </div>

        <div className="mb-6 p-4 rounded-xl bg-surface-container-low border border-outline-variant/50 flex flex-wrap items-center justify-between gap-4 font-mono text-[11px]">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex items-center gap-1.5 text-primary font-semibold">
              <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
              6/6 tests pass after the fix
            </span>
            <span className="text-outline">|</span>
            <span className="text-on-surface-variant">original code: 1/6</span>
            <span className="text-outline">|</span>
            <span className="text-on-surface-variant">security scan: no new findings</span>
          </div>
          <div className="flex items-center gap-3 text-on-surface-variant">
            <span>
              Tests: <span className="text-white">Python unittest</span>
            </span>
            <span className="text-outline">|</span>
            <span>
              Policy gate: <span className="text-secondary font-medium">pass</span>
            </span>
          </div>
        </div>

        <div className={`grid grid-cols-1 gap-5 ${unified ? "lg:grid-cols-1" : "lg:grid-cols-2"}`}>
          <div className="rounded-xl bg-surface-container-low border border-outline-variant/60 shadow-xl overflow-hidden flex flex-col">
            <div className="h-10 px-4 bg-[#0d111a] border-b border-outline-variant/40 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-error" />
                <span className="font-mono text-[10px] text-error uppercase font-medium tracking-wide">Original code · attempt #0</span>
              </div>
              <span className="font-mono text-[11px] text-on-surface-variant">1/6 tests</span>
            </div>
            <div className="p-4 font-mono text-[13px] bg-[#07090e] flex-1 overflow-x-auto flex flex-col gap-3">
              <div className="p-3 rounded bg-error/10 border border-error/25 text-error flex flex-col gap-1 text-[11px]">
                <span className="font-medium">FAIL: test_first_page</span>
                <span>AssertionError: [4, 5, 6] != [1, 2, 3]</span>
              </div>
              <Code lines={BEFORE} />
            </div>
            <div className="mt-auto p-3 bg-[#0a0d14] border-t border-outline-variant/40 text-on-surface-variant flex items-center justify-between font-mono text-[11px]">
              <span>Tests fail on the original code</span>
              <span className="text-error uppercase font-semibold">FAILED (5)</span>
            </div>
          </div>

          <div className="rounded-xl bg-surface-container-low border border-outline-variant/60 shadow-xl overflow-hidden flex flex-col">
            <div className="h-10 px-4 bg-[#0d111a] border-b border-outline-variant/40 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                <span className="font-mono text-[10px] text-primary uppercase font-medium tracking-wide">Winning patch · attempt #5</span>
              </div>
              <span className="font-mono text-[11px] text-secondary">Nebius Sandbox</span>
            </div>
            <div className="p-4 font-mono text-[13px] bg-[#07090e] flex-1 overflow-x-auto flex flex-col gap-3">
              <div className="p-3 rounded bg-primary/10 border border-primary/25 text-primary flex flex-col gap-0.5 text-[11px]">
                <span className="font-medium">Ran 6 tests · OK</span>
                <span className="text-on-surface-variant font-mono text-[10px]">policy gate: pass · security scan: clean</span>
              </div>
              <Code lines={AFTER} />
            </div>
            <div className="mt-auto p-3 bg-[#0a0d14] border-t border-outline-variant/40 text-on-surface-variant flex items-center justify-between font-mono text-[11px]">
              <span className="text-primary flex items-center gap-1">
                <span className="material-symbols-outlined text-[14px]">done_all</span>
                All tests pass in the sandbox
              </span>
              <span className="text-primary uppercase font-semibold">PR for human review</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
