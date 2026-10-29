import Link from "next/link";

const STAGES = [
  { icon: "verified_user", title: "Input guard", detail: "NeMo Guardrails screens the issue text", tone: "text-primary" },
  { icon: "troubleshoot", title: "Triage agent", detail: "Finds the cause, picks 3 strategies", tone: "text-secondary" },
  { icon: "call_split", title: "Parallel proposers", detail: "3 fixes, 3 isolated Nebius Sandboxes", tone: "text-secondary" },
  { icon: "psychology", title: "Critic", detail: "Keeps the promising fixes, drops the rest", tone: "text-secondary" },
  { icon: "policy", title: "Policy gate + security scan", detail: "Deterministic rules, then a scanner", tone: "text-primary" },
  { icon: "call_merge", title: "Pull request", detail: "Opened with the proof; a human merges", tone: "text-primary" },
];

const LOG: { t: string; tag: string; tagCls: string; text: React.ReactNode; cls?: string }[] = [
  { t: "0.10s", tag: "GUARD", tagCls: "text-primary", text: "input: pass" },
  { t: "0.33s", tag: "TRIAGE", tagCls: "text-secondary", text: "start index treats `page` as 0-indexed; no guard for page < 1" },
  { t: "0.45s", tag: "NODE #0", tagCls: "text-white/70", text: "original code: 1/6 tests", cls: "text-error/90 pl-3 border-l-2 border-error/50" },
  { t: "1.1s", tag: "NODE #1", tagCls: "text-white/70", text: "off-by-one shift: 1/6 tests" },
  { t: "1.5s", tag: "NODE #2", tagCls: "text-white/70", text: "fix core computation: 4/6 tests" },
  { t: "1.9s", tag: "NODE #3", tagCls: "text-error", text: "blocked by policy gate (shell access)", cls: "text-error/90" },
  { t: "2.2s", tag: "CRITIC", tagCls: "text-secondary", text: "keep #2, add input validation" },
  { t: "3.5s", tag: "NODE #4", tagCls: "text-amber-300", text: "6/6 tests, but security scan flags eval()" },
  { t: "4.0s", tag: "NODE #5", tagCls: "text-primary", text: "6/6 tests, clean scan: winner", cls: "text-primary pl-3 border-l-2 border-primary/70" },
  { t: "4.6s", tag: "GUARD", tagCls: "text-primary", text: "policy: pass · output: pass" },
];

export default function ProverDashboard() {
  return (
    <div
      id="prover-dashboard"
      className="w-full mt-12 max-w-6xl rounded-xl bg-[#090c12] border border-outline-variant/70 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.8),0_0_30px_rgba(16,185,129,0.1)] relative overflow-hidden text-left scroll-mt-20"
    >
      {/* Window top bar */}
      <div className="h-11 px-4 bg-[#0d111a] border-b border-outline-variant/60 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#ef4444]/80" />
            <span className="w-2.5 h-2.5 rounded-full bg-[#f59e0b]/80" />
            <span className="w-2.5 h-2.5 rounded-full bg-[#10b981]/80" />
          </div>
          <span className="h-3.5 w-px bg-outline-variant/70 mx-1" />
          <div className="flex items-center gap-2 font-mono text-[11px] text-on-surface-variant min-w-0">
            <span className="material-symbols-outlined text-[14px] text-secondary">account_tree</span>
            <span className="text-white/90 truncate">example run · paginate() skips the first page</span>
          </div>
        </div>
        <Link
          href="/try"
          className="shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded bg-primary/10 border border-primary/30 text-primary font-mono text-[11px] hover:bg-primary/20"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          <span>Run it live</span>
        </Link>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-outline-variant/60 bg-[#090c12]">
        {/* Left rail */}
        <div className="lg:col-span-3 p-3.5 bg-[#0b0f17] flex flex-col gap-3">
          <div className="flex items-center justify-between pb-2 border-b border-outline-variant/40">
            <span className="text-[10px] font-mono uppercase tracking-wider text-on-surface-variant">Agent team</span>
            <span className="font-mono text-[10px] text-primary">LangGraph</span>
          </div>
          <div className="flex flex-col gap-2 font-mono text-[11px]">
            {STAGES.map((s) => (
              <div key={s.title} className="p-2.5 rounded-lg bg-surface-container-low/60 border border-outline-variant/40 flex items-start gap-2.5">
                <span className={`material-symbols-outlined text-[16px] mt-0.5 ${s.tone}`}>{s.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-white font-medium">{s.title}</div>
                  <p className="text-on-surface-variant text-[10px]">{s.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Center event stream */}
        <div className="lg:col-span-5 p-4 bg-[#070a0f] font-mono text-[11px] leading-relaxed flex flex-col justify-between">
          <div className="space-y-1.5 overflow-hidden">
            <div className="text-on-surface-variant/70 flex items-center justify-between border-b border-outline-variant/30 pb-1.5 mb-2">
              <span>GET /api/runs/:id/events</span>
              <span className="text-[10px] text-outline">server-sent events</span>
            </div>
            {LOG.map((l) => (
              <div key={l.t + l.tag} className={l.cls || "text-on-surface-variant"}>
                <span className="text-secondary">[{l.t}]</span> <span className={l.tagCls}>{l.tag}</span> {l.text}
              </div>
            ))}
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center gap-2 text-[10px] text-on-surface-variant">
            <span className="text-primary font-semibold">●</span>
            <span>Illustration of a scripted run. Timings vary with the model and sandbox.</span>
          </div>
        </div>

        {/* Right diff */}
        <div className="lg:col-span-4 p-3.5 bg-[#0b0e15] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-outline-variant/40 mb-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-on-surface-variant">Winning diff (#5)</span>
              <span className="font-mono text-[10px] text-primary bg-primary/10 px-1.5 py-0.5 rounded border border-primary/30">6/6 tests</span>
            </div>
            <div className="rounded bg-[#07090e] border border-outline-variant/40 p-2.5 font-mono text-[11px] space-y-1 overflow-x-auto [font-variant-ligatures:none]">
              <div className="text-outline text-[10px]"># pagination.py</div>
              <div className="text-on-surface-variant whitespace-pre">def paginate(items, page, per_page):</div>
              <div className="bg-primary/15 text-primary px-1 rounded whitespace-pre">+    if page &lt; 1:</div>
              <div className="bg-primary/15 text-primary px-1 rounded whitespace-pre">+        raise ValueError(&quot;page must be &gt;= 1&quot;)</div>
              <div className="bg-error/15 text-error px-1 rounded whitespace-pre">-    start = page * per_page</div>
              <div className="bg-primary/15 text-primary px-1 rounded whitespace-pre">+    start = (page - 1) * per_page</div>
              <div className="text-on-surface-variant whitespace-pre">     return items[start:start + per_page]</div>
            </div>
          </div>
          <div className="mt-3 p-2.5 rounded bg-surface-container-low border border-outline-variant/40 flex flex-col gap-1.5 font-mono text-[10px]">
            <div className="flex items-center justify-between">
              <span className="text-primary flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px]">fact_check</span>
                PROOF = THE TEST RUN
              </span>
              <span className="text-outline">unittest</span>
            </div>
            <div className="text-white/90 bg-[#07090e] p-1.5 rounded border border-outline-variant/30">Ran 6 tests ... OK</div>
            <div className="flex items-center justify-between text-on-surface-variant pt-1">
              <span>Pull request: opened, Slack alert sent</span>
              <span className="text-primary font-medium">Waiting for a human</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
