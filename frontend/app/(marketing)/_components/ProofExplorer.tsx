"use client";

import { useState } from "react";

export default function ProofExplorer() {
  const [unified, setUnified] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [rerunLabel, setRerunLabel] = useState("Re-run Sandbox");

  const rerun = () => {
    if (rerunning) return;
    setRerunning(true);
    setRerunLabel("Booting sandbox...");
    window.setTimeout(() => {
      setRerunLabel("Verified in 12.8ms — all 14 tests green");
      setRerunning(false);
      window.setTimeout(() => setRerunLabel("Re-run Sandbox"), 2200);
    }, 700);
  };

  return (
    <section
      id="proof-explorer"
      className="w-full bg-[#090c12] border-y border-outline-variant/50 py-20 lg:py-28 scroll-mt-14"
    >
      <div className="max-w-7xl mx-auto px-4 lg:px-8">
        <div className="flex flex-col md:flex-row md:items-end justify-between mb-8 gap-4">
          <div>
            <div className="font-mono text-[11px] uppercase tracking-wider text-primary">
              LIVE PROOF INSPECTOR
            </div>
            <h2 className="mt-2 text-2xl lg:text-3xl text-white font-semibold tracking-tight">
              The Before &amp; After Proof Engine
            </h2>
            <p className="mt-2 text-on-surface-variant text-[13px] max-w-lg">
              Compare unverified runtime failures with the cryptographically sealed
              patch after isolated Micro-VM execution.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setUnified((v) => !v)}
              className="px-3.5 py-1.5 rounded-lg bg-surface-container border border-outline-variant/60 text-white font-mono text-[12px] hover:bg-surface-bright transition-colors flex items-center gap-1.5"
            >
              <span className="material-symbols-outlined text-[15px]">splitscreen</span>
              <span>Mode: {unified ? "Unified Diff" : "Side-by-Side"}</span>
            </button>
            <button
              onClick={rerun}
              className="px-3.5 py-1.5 rounded-lg bg-primary/10 border border-primary/30 text-primary font-mono text-[12px] hover:bg-primary/20 transition-colors flex items-center gap-1.5 disabled:opacity-70"
              disabled={rerunning}
            >
              <span
                className={`material-symbols-outlined text-[15px] ${rerunning ? "animate-spin" : ""}`}
              >
                refresh
              </span>
              <span>{rerunLabel}</span>
            </button>
          </div>
        </div>

        <div className="mb-6 p-4 rounded-xl bg-surface-container-low border border-outline-variant/50 flex flex-wrap items-center justify-between gap-4 font-mono text-[11px]">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-primary font-semibold">
              <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
              14/14 Tests Passed
            </span>
            <span className="text-outline">|</span>
            <span className="text-on-surface-variant">0 Regressions</span>
            <span className="text-outline">|</span>
            <span className="text-on-surface-variant">Memory Leaks: 0.00KB</span>
          </div>
          <div className="flex items-center gap-3 text-on-surface-variant">
            <span>
              Target: <span className="text-white">Node v20.11 / V8 12.0</span>
            </span>
            <span className="text-outline">|</span>
            <span>
              Time in Sandbox: <span className="text-secondary font-medium">248ms</span>
            </span>
          </div>
        </div>

        <div className={`grid grid-cols-1 gap-5 ${unified ? "lg:grid-cols-1" : "lg:grid-cols-2"}`}>
          {/* Failing run */}
          <div className="rounded-xl bg-surface-container-low border border-outline-variant/60 shadow-xl overflow-hidden flex flex-col">
            <div className="h-10 px-4 bg-[#0d111a] border-b border-outline-variant/40 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-error" />
                <span className="font-mono text-[10px] text-error uppercase font-medium tracking-wide">
                  FAILING RUN #8412 — Production Issue
                </span>
              </div>
              <span className="font-mono text-[11px] text-on-surface-variant">CI Run: 41.2s ago</span>
            </div>
            <div className="p-4 font-mono text-[13px] bg-[#07090e] flex-1 overflow-x-auto flex flex-col gap-3">
              <div className="p-3 rounded bg-error/10 border border-error/25 text-error flex flex-col gap-1 text-[11px]">
                <span className="font-medium">FAIL src/auth/session_manager.test.ts:42</span>
                <span>TypeError: Cannot read properties of undefined (reading &apos;token_id&apos;)</span>
              </div>
              <div className="flex flex-col text-on-surface-variant font-mono text-[13px]">
                <div className="flex items-center gap-4 py-0.5 px-2">
                  <span className="w-8 text-outline text-right select-none">139</span>
                  <span>async function validateSession(req: IncomingRequest) {"{"}</span>
                </div>
                <div className="flex items-center gap-4 py-0.5 px-2">
                  <span className="w-8 text-outline text-right select-none">140</span>
                  <span> const session = await db.sessions.lookup(req.sid);</span>
                </div>
                <div className="flex items-center gap-4 py-0.5 px-2 bg-error/15 text-error font-medium">
                  <span className="w-8 text-error font-medium text-right select-none">141</span>
                  <span>- const verified = session.token_id === req.token;</span>
                </div>
                <div className="flex items-center gap-4 py-0.5 px-2">
                  <span className="w-8 text-outline text-right select-none">142</span>
                  <span> return verified;</span>
                </div>
                <div className="flex items-center gap-4 py-0.5 px-2">
                  <span className="w-8 text-outline text-right select-none">143</span>
                  <span>{"}"}</span>
                </div>
              </div>
            </div>
            <div className="mt-auto p-3 bg-[#0a0d14] border-t border-outline-variant/40 text-on-surface-variant flex items-center justify-between font-mono text-[11px]">
              <span>Status: Pipeline halted on assertion failure</span>
              <span className="text-error uppercase font-semibold">Exit Code 1</span>
            </div>
          </div>

          {/* Proven patch */}
          <div className="rounded-xl bg-surface-container-low border border-outline-variant/60 shadow-xl overflow-hidden flex flex-col">
            <div className="h-10 px-4 bg-[#0d111a] border-b border-outline-variant/40 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                <span className="font-mono text-[10px] text-primary uppercase font-medium tracking-wide">
                  PROVEN PATCH #8412 — Applied &amp; Verified
                </span>
              </div>
              <span className="font-mono text-[11px] text-secondary">Hermetic Micro-VM: 248ms</span>
            </div>
            <div className="p-4 font-mono text-[13px] bg-[#07090e] flex-1 overflow-x-auto flex flex-col gap-3">
              <div className="p-3 rounded bg-primary/10 border border-primary/25 text-primary flex flex-col gap-0.5 text-[11px]">
                <span className="font-medium">✓ PASS src/auth/session_manager.test.ts (14 tests passed, 0 failed)</span>
                <span className="text-on-surface-variant font-mono text-[10px]">
                  ✓ Memory leak check: CLEAN (0 leaks detected in 1,000 iterations)
                </span>
              </div>
              <div className="flex flex-col text-on-surface font-mono text-[13px]">
                <div className="flex items-center gap-4 py-0.5 px-2 text-on-surface-variant">
                  <span className="w-8 text-outline text-right select-none">139</span>
                  <span>async function validateSession(req: IncomingRequest) {"{"}</span>
                </div>
                <div className="flex items-center gap-4 py-0.5 px-2 text-on-surface-variant">
                  <span className="w-8 text-outline text-right select-none">140</span>
                  <span> const session = await db.sessions.lookup(req.sid);</span>
                </div>
                <div className="flex items-center gap-4 py-0.5 px-2 bg-primary/15 text-primary font-medium">
                  <span className="w-8 text-primary font-medium text-right select-none">141</span>
                  <span>+ if (!session?.token_id) throw new AuthExpiredError();</span>
                </div>
                <div className="flex items-center gap-4 py-0.5 px-2 bg-primary/15 text-primary font-medium">
                  <span className="w-8 text-primary font-medium text-right select-none">142</span>
                  <span>+ const verified = session.token_id === req.token;</span>
                </div>
                <div className="flex items-center gap-4 py-0.5 px-2 text-on-surface-variant">
                  <span className="w-8 text-outline text-right select-none">143</span>
                  <span> return verified;</span>
                </div>
              </div>
            </div>
            <div className="mt-auto p-3 bg-[#0a0d14] border-t border-outline-variant/40 text-on-surface-variant flex items-center justify-between font-mono text-[11px]">
              <span className="text-primary flex items-center gap-1">
                <span className="material-symbols-outlined text-[14px]">done_all</span>
                100% Hermetic Execution Verified
              </span>
              <span className="text-primary uppercase font-semibold">PR #8412 Ready to Merge</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
