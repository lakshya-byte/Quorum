"use client";

import { useRef } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(ScrollTrigger, useGSAP);

export default function ArchitectureBento() {
  const rootRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const cards = gsap.utils.toArray<HTMLElement>(".bento-card", rootRef.current!);
      gsap.set(cards, { opacity: 0, y: 24 });
      gsap.to(cards, {
        opacity: 1,
        y: 0,
        duration: 0.6,
        ease: "power2.out",
        stagger: 0.08,
        scrollTrigger: {
          trigger: rootRef.current,
          start: "top 78%",
          once: true,
        },
      });
    },
    { scope: rootRef }
  );

  return (
    <section
      ref={rootRef}
      id="architecture"
      className="w-full max-w-7xl mx-auto px-4 lg:px-8 py-20 lg:py-28 scroll-mt-14"
    >
      <div className="flex flex-col md:flex-row md:items-end justify-between mb-12 gap-4">
        <div>
          <div className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-secondary">
            <span className="material-symbols-outlined text-[15px]">architecture</span>
            ENGINEERED FOR HERMETIC PRECISION
          </div>
          <h2 className="mt-2 text-2xl lg:text-3xl text-white font-semibold tracking-tight">
            Full-Stack Autonomous Prover Architecture
          </h2>
        </div>
        <p className="text-[14px] text-on-surface-variant max-w-md">
          PatchLoop replaces conversational guessing with branch-bounded symbolic
          synthesis and sub-millisecond Firecracker hypervisor isolation.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {/* Card 1: Micro-VM isolation (wide) */}
        <div className="bento-card lg:col-span-2 rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative overflow-hidden group">
          <div className="absolute top-0 right-0 w-80 h-80 bg-primary/5 rounded-full blur-3xl pointer-events-none" />
          <div>
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-primary border border-primary/20">
                FIRECRACKER HYPERVISOR BOUNDARY
              </span>
              <span className="font-mono text-[11px] text-secondary">sub-15ms jail</span>
            </div>
            <h3 className="text-xl text-white font-medium">
              Ephemeral Micro-VM Memory Isolation
            </h3>
            <p className="mt-1 text-on-surface-variant text-[13px] max-w-xl">
              Each patch candidate is executed within an isolated, hardware-virtualized
              guest kernel. Memory state is snapshot-restored instantly with
              copy-on-write integrity.
            </p>

            <div className="mt-6 p-4 rounded-lg bg-[#07090e] border border-outline-variant/50 flex flex-col gap-3 font-mono text-[11px]">
              <div className="flex items-center justify-between text-outline text-[10px]">
                <span>HOST PERIMETER (KVM / /dev/net/tun DISABLED)</span>
                <span className="text-primary font-medium">JAILED GUEST</span>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div className="p-3 rounded bg-surface-container-high/60 border border-outline-variant/40 flex flex-col gap-1">
                  <span className="text-white font-medium text-[11px]">Ring 0: Guest Kernel</span>
                  <span className="text-on-surface-variant text-[10px]">6.1.42 Hermetic Strip</span>
                  <span className="text-primary text-[10px]">Init: 3.4ms</span>
                </div>
                <div className="p-3 rounded bg-surface-container-high/60 border border-outline-variant/40 flex flex-col gap-1">
                  <span className="text-white font-medium text-[11px]">Ring 3: AST Test Harness</span>
                  <span className="text-on-surface-variant text-[10px]">Deterministic V8/LLVM</span>
                  <span className="text-secondary text-[10px]">Cow Heap: 128MB</span>
                </div>
                <div className="p-3 rounded bg-primary/10 border border-primary/30 flex flex-col gap-1">
                  <span className="text-primary font-medium text-[11px]">Cryptographic Verifier</span>
                  <span className="text-on-surface-variant text-[10px]">Assertion Matrix</span>
                  <span className="text-primary text-[10px]">0 Regressions</span>
                </div>
              </div>
              <div className="flex items-center justify-between pt-2 border-t border-outline-variant/30 text-[10px] text-on-surface-variant">
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                  Zero network egress allowed
                </span>
                <span className="text-white">Seccomp profile: strictly enforced</span>
              </div>
            </div>
          </div>
          <div className="mt-5 flex items-center justify-between pt-3 border-t border-outline-variant/40 text-on-surface-variant font-mono text-[11px]">
            <span>Hardware virtualization acceleration</span>
            <span className="text-primary">100% Hermetic Guarantee →</span>
          </div>
        </div>

        {/* Card 2: Zero hallucinations */}
        <div className="bento-card rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative">
          <div>
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-secondary border border-secondary/20">
                FORMAL PROOF
              </span>
              <span className="material-symbols-outlined text-secondary text-[20px]">fact_check</span>
            </div>
            <h3 className="text-xl text-white font-medium">Zero Hallucinations</h3>
            <p className="mt-1 text-on-surface-variant text-[13px]">
              Speculative suggestions are banned. An AST invariant solver checks boundary
              types before the patch reaches CI.
            </p>

            <div className="mt-5 p-3 rounded-lg bg-[#07090e] border border-outline-variant/50 space-y-2 font-mono text-[10px]">
              {[
                { label: "Type Invariance Check", value: "PASSED (100%)", bar: "bg-primary" },
                { label: "Null Pointer Safety Proof", value: "VERIFIED (100%)", bar: "bg-primary" },
                { label: "Non-Destructive AST Edit", value: "SEALED (100%)", bar: "bg-secondary" },
              ].map((row) => (
                <div key={row.label}>
                  <div className="flex justify-between items-center text-on-surface-variant pt-1 first:pt-0">
                    <span>{row.label}</span>
                    <span className="text-primary">{row.value}</span>
                  </div>
                  <div className="w-full h-1.5 bg-surface-container rounded-full overflow-hidden mt-1">
                    <div className={`h-full ${row.bar} rounded-full w-full`} />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center justify-between font-mono text-[11px] text-primary">
            <span>0 Speculative PRs Generated</span>
            <span className="material-symbols-outlined text-[16px]">verified</span>
          </div>
        </div>

        {/* Card 3: Nemotron + Nebius */}
        <div className="bento-card rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative">
          <div>
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-primary border border-primary/20">
                INFERENCE FABRIC
              </span>
              <span className="font-mono text-[11px] text-primary">1,240 tok/sec</span>
            </div>
            <h3 className="text-xl text-white font-medium">Nemotron-70B + Nebius</h3>
            <p className="mt-1 text-on-surface-variant text-[13px]">
              Ultra-low latency symbolic patch reasoning hosted on Nebius
              high-throughput Token Factory infrastructure.
            </p>

            <div className="mt-5 p-3 rounded-lg bg-[#07090e] border border-outline-variant/50 space-y-2 font-mono text-[11px]">
              <div className="flex items-center justify-between text-on-surface-variant text-[10px]">
                <span>INFERENCE WATERFALL</span>
                <span className="text-secondary">&lt;48ms completion</span>
              </div>
              <div className="flex items-end gap-1 h-9 px-1 pt-1">
                <div className="w-1/6 bg-secondary/30 h-3 rounded-t" />
                <div className="w-1/6 bg-secondary/50 h-5 rounded-t" />
                <div className="w-1/6 bg-primary/70 h-8 rounded-t" />
                <div className="w-1/6 bg-primary h-9 rounded-t" />
                <div className="w-1/6 bg-primary/90 h-7 rounded-t" />
                <div className="w-1/6 bg-secondary/80 h-6 rounded-t" />
              </div>
              <div className="flex justify-between text-[10px] text-outline pt-1">
                <span>Prompt AST (1.2k)</span>
                <span className="text-white">1,240 tokens/s peak</span>
              </div>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center justify-between text-on-surface-variant font-mono text-[11px]">
            <span>Sub-second generation loop</span>
            <span className="text-white font-medium">&lt;480ms end-to-end</span>
          </div>
        </div>

        {/* Card 4: CI/CD bot */}
        <div className="bento-card rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative">
          <div>
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant">
                SEAMLESS WORKFLOW
              </span>
              <span className="material-symbols-outlined text-[16px] text-on-surface-variant">merge</span>
            </div>
            <h3 className="text-xl text-white font-medium">CI/CD Direct Bot</h3>
            <p className="mt-1 text-on-surface-variant text-[13px]">
              Native GitHub Actions, GitLab CI, and Buildkite integrations
              automatically open ready-to-merge PRs.
            </p>

            <div className="mt-5 p-3 rounded-lg bg-[#07090e] border border-outline-variant/50 space-y-2 font-mono text-[11px]">
              <div className="flex items-center gap-2 text-white">
                <span className="material-symbols-outlined text-primary text-[15px]">check_circle</span>
                <span className="font-medium truncate">PatchLoop Auto-Verifier / PR #8412</span>
              </div>
              <div className="pl-5 text-[10px] text-on-surface-variant flex flex-col gap-0.5">
                <span>✓ Micro-VM compiled successfully (248ms)</span>
                <span>✓ Cryptographic proof signature validated</span>
              </div>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center justify-between font-mono text-[11px] text-secondary">
            <span>GitHub · GitLab · Buildkite</span>
            <span>Zero config required</span>
          </div>
        </div>

        {/* Card 5: Enterprise assurance (wide) */}
        <div className="bento-card lg:col-span-2 rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative">
          <div>
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-primary border border-primary/20">
                ENTERPRISE ASSURANCE
              </span>
              <span className="font-mono text-[11px] text-white">SOC2 TYPE II · HIPAA READY</span>
            </div>
            <h3 className="text-xl text-white font-medium">
              Air-Gapped &amp; Private VPC Enclaves
            </h3>
            <p className="mt-1 text-on-surface-variant text-[13px] max-w-xl">
              Deploy entirely within AWS Nitro Enclaves, GCP Confidential VMs, or
              on-prem air-gapped clusters. Source code AST never traverses external
              networks.
            </p>

            <div className="mt-5 p-3 rounded-lg bg-[#07090e] border border-outline-variant/50 font-mono text-[10px] text-on-surface-variant space-y-1">
              <div className="flex justify-between text-outline">
                <span>[AUDIT_ENCLAVE_DAEMON]</span>
                <span className="text-primary">ISOLATION INTEGRITY: 100%</span>
              </div>
              <div>
                [14:22:01.092] VPC egress firewall:{" "}
                <span className="text-white">DENY ALL OUTBOUND</span> (0 packets transmitted)
              </div>
              <div>
                [14:22:01.094] Ephemeral micro-VM storage: Shredded with{" "}
                <span className="text-white">DoD 5220.22-M wipe</span>
              </div>
              <div>
                [14:22:01.099] Cryptographic proof pinned to immutable audit trail:{" "}
                <span className="text-secondary">0x8a92f0...</span>
              </div>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center justify-between text-on-surface-variant font-mono text-[11px]">
            <span>Zero telemetry egress policy</span>
            <span className="text-primary font-medium">Review Security Whitepaper →</span>
          </div>
        </div>
      </div>
    </section>
  );
}
