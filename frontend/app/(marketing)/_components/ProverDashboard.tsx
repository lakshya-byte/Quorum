export default function ProverDashboard() {
  return (
    <div
      id="prover-dashboard"
      className="w-full mt-12 max-w-6xl rounded-xl bg-[#090c12] border border-outline-variant/70 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.8),0_0_30px_rgba(16,185,129,0.1)] relative overflow-hidden text-left scroll-mt-20"
    >
      {/* Window top bar */}
      <div className="h-11 px-4 bg-[#0d111a] border-b border-outline-variant/60 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-[#ef4444]/80" />
            <span className="w-2.5 h-2.5 rounded-full bg-[#f59e0b]/80" />
            <span className="w-2.5 h-2.5 rounded-full bg-[#10b981]/80" />
          </div>
          <span className="h-3.5 w-px bg-outline-variant/70 mx-1" />
          <div className="flex items-center gap-2 font-mono text-[11px] text-on-surface-variant">
            <span className="material-symbols-outlined text-[14px] text-secondary">memory</span>
            <span className="text-white/90">patchloop-daemon://fc-guest-node-918</span>
            <span className="text-outline text-[11px]">kernel 6.1.42-hermetic</span>
          </div>
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px]">
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-primary/10 border border-primary/30 text-primary">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-ping" />
            <span>PROVER RUNNING</span>
          </div>
          <span className="hidden sm:inline text-on-surface-variant/80">
            TTFT: <span className="text-secondary font-medium">&lt;14.2ms</span>
          </span>
          <span className="hidden sm:inline text-on-surface-variant/80">
            Mem: <span className="text-white">128MB</span>/512MB
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-outline-variant/60 bg-[#090c12]">
        {/* Left rail */}
        <div className="lg:col-span-3 p-3.5 bg-[#0b0f17] flex flex-col gap-3">
          <div className="flex items-center justify-between pb-2 border-b border-outline-variant/40">
            <span className="text-[10px] font-mono uppercase tracking-wider text-on-surface-variant">
              Verification DAG
            </span>
            <span className="font-mono text-[10px] text-primary">4/4 STAGES OK</span>
          </div>
          <div className="flex flex-col gap-2 font-mono text-[11px]">
            <div className="p-2.5 rounded-lg bg-surface-container-low/60 border border-outline-variant/40 flex items-start gap-2.5">
              <span className="material-symbols-outlined text-primary text-[16px] mt-0.5">check_circle</span>
              <div className="flex-1 min-w-0">
                <div className="text-white font-medium flex items-center justify-between">
                  <span>AST Parse &amp; Fault</span>
                  <span className="text-outline text-[10px]">1.8ms</span>
                </div>
                <p className="text-on-surface-variant text-[10px] truncate">
                  Fault localized: auth/session.ts:141
                </p>
              </div>
            </div>
            <div className="p-2.5 rounded-lg bg-surface-container-low/60 border border-outline-variant/40 flex items-start gap-2.5">
              <span className="material-symbols-outlined text-secondary text-[16px] mt-0.5">neurology</span>
              <div className="flex-1 min-w-0">
                <div className="text-white font-medium flex items-center justify-between">
                  <span>Symbolic Gen</span>
                  <span className="text-outline text-[10px]">48ms</span>
                </div>
                <p className="text-on-surface-variant text-[10px] truncate">
                  Nemotron-70B · 3 candidate ASTs
                </p>
              </div>
            </div>
            <div className="p-2.5 rounded-lg bg-surface-container-low/60 border border-outline-variant/40 flex items-start gap-2.5">
              <span className="material-symbols-outlined text-secondary text-[16px] mt-0.5">bolt</span>
              <div className="flex-1 min-w-0">
                <div className="text-white font-medium flex items-center justify-between">
                  <span>Firecracker Boot</span>
                  <span className="text-outline text-[10px]">8.2ms</span>
                </div>
                <p className="text-on-surface-variant text-[10px] truncate">
                  Clean jail: /dev/kvm isolated
                </p>
              </div>
            </div>
            <div className="p-2.5 rounded-lg bg-primary/10 border border-primary/30 flex items-start gap-2.5">
              <span className="material-symbols-outlined text-primary text-[16px] mt-0.5 animate-pulse">verified</span>
              <div className="flex-1 min-w-0">
                <div className="text-primary font-medium flex items-center justify-between">
                  <span>Formal Verify</span>
                  <span className="text-primary text-[10px]">PASS</span>
                </div>
                <p className="text-primary/80 text-[10px] truncate">
                  14/14 tests green · 0 regression
                </p>
              </div>
            </div>
          </div>
          <div className="mt-auto pt-3 border-t border-outline-variant/40 flex flex-col gap-1.5 font-mono text-[10px] text-on-surface-variant">
            <div className="flex justify-between">
              <span>Micro-VM PID:</span>
              <span className="text-white">10492</span>
            </div>
            <div className="flex justify-between">
              <span>Proof Digest:</span>
              <span className="text-secondary">sha256:0x9f88c7</span>
            </div>
            <div className="flex justify-between">
              <span>Isolation Level:</span>
              <span className="text-primary">Hermetic L3</span>
            </div>
          </div>
        </div>

        {/* Center log stream */}
        <div className="lg:col-span-5 p-4 bg-[#070a0f] font-mono text-[11px] leading-relaxed flex flex-col justify-between">
          <div className="space-y-1.5 overflow-hidden">
            <div className="text-on-surface-variant/70 flex items-center justify-between border-b border-outline-variant/30 pb-1.5 mb-2">
              <span>guest://sandbox-runtime.log</span>
              <span className="text-[10px] text-outline">STDOUT / DRAIN ACTIVE</span>
            </div>
            <div className="text-on-surface-variant">
              <span className="text-secondary">[00:00:00.000]</span>{" "}
              <span className="text-white/60">kvm_init()</span> allocating 2 vCPUs, 512MB
              hermetic mem ring
            </div>
            <div className="text-on-surface-variant">
              <span className="text-secondary">[00:00:00.008]</span>{" "}
              <span className="text-primary">FIRECRACKER</span> Guest micro-VM booted in{" "}
              <span className="text-primary font-medium">8.2ms</span>
            </div>
            <div className="text-on-surface-variant">
              <span className="text-secondary">[00:00:00.014]</span>{" "}
              <span className="text-secondary">AST_PARSER</span> Loading target AST{" "}
              <code className="text-white">src/auth/session_manager.ts</code>
            </div>
            <div className="text-error/90 pl-3 border-l-2 border-error/50">
              [00:00:00.022] FAIL: TypeError: Cannot read properties of undefined
              (reading &apos;token_id&apos;)
            </div>
            <div className="text-on-surface-variant">
              <span className="text-secondary">[00:00:00.054]</span>{" "}
              <span className="text-secondary">NEBIUS_ENGINE</span> Synthesizing patch
              candidates using Nemotron-70B...
            </div>
            <div className="text-on-surface-variant">
              <span className="text-secondary">[00:00:00.098]</span> Candidate #2 selected
              (structural invariance score: <span className="text-white">0.994</span>)
            </div>
            <div className="text-on-surface-variant">
              <span className="text-secondary">[00:00:00.112]</span> Injecting patch bytecode
              into ephemeral test harness...
            </div>
            <div className="text-primary pl-3 border-l-2 border-primary/70">
              [00:00:00.174] PASS src/auth/session_manager.test.ts (14/14 assertions OK)
            </div>
            <div className="text-on-surface-variant">
              <span className="text-secondary">[00:00:00.188]</span>{" "}
              <span className="text-primary">PROOF_ENGINE</span> Sealed cryptographic proof:{" "}
              <span className="text-white">0x9f88c74a12ec</span>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center justify-between text-[10px]">
            <div className="flex items-center gap-2">
              <span className="text-primary font-semibold">●</span>
              <span className="text-on-surface-variant">
                VM Sandbox Tear-down: Scheduled (0ms leakage)
              </span>
            </div>
          </div>
        </div>

        {/* Right diff / proof */}
        <div className="lg:col-span-4 p-3.5 bg-[#0b0e15] flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-outline-variant/40 mb-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-on-surface-variant">
                Synthetic Patch Diff
              </span>
              <span className="font-mono text-[10px] text-primary bg-primary/10 px-1.5 py-0.5 rounded border border-primary/30">
                VERIFIED PR #8412
              </span>
            </div>
            <div className="rounded bg-[#07090e] border border-outline-variant/40 p-2.5 font-mono text-[11px] space-y-1">
              <div className="text-outline text-[10px]">// src/auth/session_manager.ts:139</div>
              <div className="text-on-surface-variant">139 async function validateSession(req) {"{"}</div>
              <div className="text-on-surface-variant">140 const session = await db.lookup(req.sid);</div>
              <div className="bg-error/15 text-error px-1 rounded flex items-center">
                <span className="w-5 text-error/60 text-[10px]">-</span>
                <span>const ok = session.token_id === req.t;</span>
              </div>
              <div className="bg-primary/15 text-primary px-1 rounded flex items-center font-medium">
                <span className="w-5 text-primary/60 text-[10px]">+</span>
                <span>if (!session?.token_id) throw new Expired();</span>
              </div>
              <div className="bg-primary/15 text-primary px-1 rounded flex items-center font-medium">
                <span className="w-5 text-primary/60 text-[10px]">+</span>
                <span>const ok = session.token_id === req.t;</span>
              </div>
              <div className="text-on-surface-variant">143 return ok;</div>
              <div className="text-on-surface-variant">144 {"}"}</div>
            </div>
          </div>
          <div className="mt-3 p-2.5 rounded bg-surface-container-low border border-outline-variant/40 flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono text-primary flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px]">shield</span>
                <span>CRYPTOGRAPHIC PROOF</span>
              </span>
              <span className="font-mono text-[10px] text-outline">SHA-256</span>
            </div>
            <div className="font-mono text-[10px] text-white/90 break-all bg-[#07090e] p-1.5 rounded border border-outline-variant/30">
              0x9f88c74a12ec829b47e293041a99ef87b0a114
            </div>
            <div className="flex items-center justify-between text-[10px] text-on-surface-variant pt-1">
              <span>Pull Request: Auto-certified</span>
              <span className="text-primary font-medium">Ready to Merge</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
