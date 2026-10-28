"use client";

import { useState } from "react";
import { smoothScrollTo } from "../../_lib/lenis";

const METHODS = [
  {
    id: "cli",
    label: "CLI Installer",
    command: "curl -sSL https://patchloop.dev/install.sh | bash",
  },
  {
    id: "github",
    label: "GitHub Bot",
    command: "gh app install patchloop-bot --repo your-org/your-repo",
  },
  {
    id: "docker",
    label: "Docker Hermetic",
    command: "docker pull ghcr.io/patchloop/prover:latest",
  },
  {
    id: "terraform",
    label: "Terraform VPC",
    command: "terraform apply -var-file=patchloop.tfvars",
  },
];

export default function Quickstart() {
  const [activeId, setActiveId] = useState(METHODS[0].id);
  const [copied, setCopied] = useState(false);
  const [booting, setBooting] = useState(false);

  const active = METHODS.find((m) => m.id === activeId)!;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(active.command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  const launchDemo = () => {
    if (booting) return;
    setBooting(true);
    window.setTimeout(() => {
      setBooting(false);
      smoothScrollTo("#prover-dashboard");
    }, 500);
  };

  return (
    <section id="quickstart" className="w-full max-w-5xl mx-auto px-4 lg:px-8 py-20 lg:py-24 scroll-mt-14">
      <div className="rounded-2xl bg-surface-container-low border border-outline-variant/70 p-6 sm:p-10 shadow-2xl relative overflow-hidden">
        <div
          aria-hidden
          className="absolute -bottom-24 left-1/2 -translate-x-1/2 w-96 h-48 bg-primary/10 blur-[90px] pointer-events-none rounded-full"
        />

        <div className="text-center max-w-xl mx-auto">
          <span className="font-mono text-[11px] uppercase tracking-wider text-primary">
            DEVELOPER QUICKSTART
          </span>
          <h2 className="mt-2 text-2xl lg:text-3xl text-white font-semibold tracking-tight">
            Deploy Autonomous Verification in 60s
          </h2>
          <p className="mt-2 text-on-surface-variant text-[13px]">
            Zero configuration needed. Compatible with any Node, Python, Rust, or Go
            monorepo.
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
          <div className="flex items-center gap-2.5 overflow-x-auto font-mono text-[14px] text-white px-2">
            <span className="text-primary select-none font-semibold">$</span>
            <span className="text-secondary select-all">{active.command}</span>
          </div>
          <button
            onClick={copy}
            className="shrink-0 px-3 py-1.5 rounded bg-surface-container border border-outline-variant/50 text-on-surface-variant hover:text-white hover:bg-surface-bright transition-colors flex items-center gap-1.5 font-mono text-[11px]"
          >
            <span className="material-symbols-outlined text-[15px]">
              {copied ? "check" : "content_copy"}
            </span>
            <span className={copied ? "text-primary" : undefined}>
              {copied ? "Copied!" : "Copy"}
            </span>
          </button>
        </div>

        <div className="mt-6 max-w-2xl mx-auto grid grid-cols-1 sm:grid-cols-2 gap-3 font-mono text-[11px]">
          <div className="p-2.5 rounded bg-surface-container/60 border border-outline-variant/40 flex flex-col gap-1">
            <code className="text-primary">--hermetic=strict</code>
            <span className="text-on-surface-variant text-[10px]">
              Zero network egress micro-VM jail enforcement
            </span>
          </div>
          <div className="p-2.5 rounded bg-surface-container/60 border border-outline-variant/40 flex flex-col gap-1">
            <code className="text-secondary">--vm-pool=4</code>
            <span className="text-on-surface-variant text-[10px]">
              Pre-warm 4 Firecracker micro-VM instances for &lt;10ms runs
            </span>
          </div>
        </div>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <button
            onClick={launchDemo}
            disabled={booting}
            className="group relative inline-flex items-center justify-center gap-2 px-8 py-3 rounded-lg bg-primary text-black text-[14px] font-semibold shadow-[0_0_24px_rgba(16,185,129,0.35)] hover:bg-[#34d399] transition-all duration-200 disabled:opacity-80"
          >
            {booting ? (
              <>
                <span className="material-symbols-outlined text-[18px] animate-spin">refresh</span>
                <span>Booting Ephemeral Firecracker VM...</span>
              </>
            ) : (
              <>
                <span className="material-symbols-outlined text-[18px]">terminal</span>
                <span>Launch Live Sandbox Demo</span>
                <span className="material-symbols-outlined text-[16px] transition-transform duration-200 group-hover:translate-x-1">
                  arrow_forward
                </span>
              </>
            )}
          </button>
        </div>
      </div>
    </section>
  );
}
