"use client";

import { useRef } from "react";
import Link from "next/link";
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
            HOW PATCHLOOP WORKS
          </div>
          <h2 className="mt-2 text-2xl lg:text-3xl text-white font-semibold tracking-tight">
            Agents propose. Tests decide. Humans merge.
          </h2>
        </div>
        <p className="text-[14px] text-on-surface-variant max-w-md">
          Three services: a Next.js frontend, a Go API that owns auth, runs and pull
          requests, and an internal Python agent service that drives the LangGraph
          agent team and the sandboxes.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {/* Card 1: sandboxes (wide) */}
        <div className="bento-card lg:col-span-2 rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative overflow-hidden group">
          <div className="absolute top-0 right-0 w-80 h-80 bg-primary/5 rounded-full blur-3xl pointer-events-none" />
          <div>
            <div className="flex items-center justify-between mb-4 gap-2">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-primary border border-primary/20">
                NEBIUS SANDBOXES
              </span>
              <span className="font-mono text-[11px] text-secondary">one sandbox per attempt</span>
            </div>
            <h3 className="text-xl text-white font-medium">Parallel fixes, isolated from each other</h3>
            <p className="mt-1 text-on-surface-variant text-[13px] max-w-xl">
              Each candidate fix is written into its own isolated Nebius Sandbox together
              with the bug&apos;s tests, and run there. A broken or hostile attempt only
              affects its own sandbox; the search keeps going.
            </p>

            <div className="mt-6 p-4 rounded-lg bg-[#07090e] border border-outline-variant/50 flex flex-col gap-3 font-mono text-[11px]">
              <div className="flex items-center justify-between text-outline text-[10px] gap-2">
                <span>ROUND 1 · 3 PROPOSERS IN PARALLEL</span>
                <span className="text-primary font-medium">TESTS SCORE EACH ONE</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <div className="p-3 rounded bg-surface-container-high/60 border border-error/30 flex flex-col gap-1">
                  <span className="text-white font-medium text-[11px]">Sandbox A</span>
                  <span className="text-on-surface-variant text-[10px]">off-by-one strategy</span>
                  <span className="text-error text-[10px]">1/6 tests</span>
                </div>
                <div className="p-3 rounded bg-surface-container-high/60 border border-amber-400/30 flex flex-col gap-1">
                  <span className="text-white font-medium text-[11px]">Sandbox B</span>
                  <span className="text-on-surface-variant text-[10px]">input validation</span>
                  <span className="text-amber-300 text-[10px]">4/6 tests · kept by critic</span>
                </div>
                <div className="p-3 rounded bg-primary/10 border border-primary/30 flex flex-col gap-1">
                  <span className="text-primary font-medium text-[11px]">Round 2 · from B</span>
                  <span className="text-on-surface-variant text-[10px]">add the guard clause</span>
                  <span className="text-primary text-[10px]">6/6 tests · winner</span>
                </div>
              </div>
              <div className="flex items-center justify-between pt-2 border-t border-outline-variant/30 text-[10px] text-on-surface-variant gap-2">
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                  score = passed / total, smaller diffs win ties
                </span>
                <span className="text-white">up to 3 rounds</span>
              </div>
            </div>
          </div>
          <div className="mt-5 flex items-center justify-between pt-3 border-t border-outline-variant/40 text-on-surface-variant font-mono text-[11px]">
            <span>Watch the tree grow live</span>
            <Link href="/try" className="text-primary hover:underline">
              Open the demo →
            </Link>
          </div>
        </div>

        {/* Card 2: tests decide */}
        <div className="bento-card rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative">
          <div>
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-secondary border border-secondary/20">
                TESTS ARE THE JUDGE
              </span>
              <span className="material-symbols-outlined text-secondary text-[20px]">fact_check</span>
            </div>
            <h3 className="text-xl text-white font-medium">The model never grades itself</h3>
            <p className="mt-1 text-on-surface-variant text-[13px]">
              A fix counts as solved only when every test passes in the sandbox. The
              model&apos;s opinion of its own patch is not part of the score.
            </p>

            <div className="mt-5 p-3 rounded-lg bg-[#07090e] border border-outline-variant/50 space-y-2 font-mono text-[10px]">
              {[
                { label: "Original code (#0)", value: "1/6", w: "w-1/6", bar: "bg-error" },
                { label: "Best of round 1 (#2)", value: "4/6", w: "w-4/6", bar: "bg-amber-400" },
                { label: "Winner (#5)", value: "6/6", w: "w-full", bar: "bg-primary" },
              ].map((row) => (
                <div key={row.label}>
                  <div className="flex justify-between items-center text-on-surface-variant pt-1 first:pt-0">
                    <span>{row.label}</span>
                    <span className="text-white">{row.value} tests</span>
                  </div>
                  <div className="w-full h-1.5 bg-surface-container rounded-full overflow-hidden mt-1">
                    <div className={`h-full ${row.bar} rounded-full ${row.w}`} />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center justify-between font-mono text-[11px] text-primary">
            <span>Unsolved runs propose nothing for merge</span>
            <span className="material-symbols-outlined text-[16px]">verified</span>
          </div>
        </div>

        {/* Card 3: Nemotron + Nebius */}
        <div className="bento-card rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative">
          <div>
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-primary border border-primary/20">
                MODELS
              </span>
              <span className="material-symbols-outlined text-primary text-[20px]">neurology</span>
            </div>
            <h3 className="text-xl text-white font-medium">Nemotron via Nebius Token Factory</h3>
            <p className="mt-1 text-on-surface-variant text-[13px]">
              NVIDIA Nemotron models served by Nebius Token Factory power the agents: a
              smaller model for the first round, a larger one for deeper rounds.
            </p>

            <div className="mt-5 p-3 rounded-lg bg-[#07090e] border border-outline-variant/50 space-y-1.5 font-mono text-[11px] text-on-surface-variant">
              <div className="flex justify-between gap-2">
                <span>triage</span>
                <span className="text-white">cause + 3 strategies</span>
              </div>
              <div className="flex justify-between gap-2">
                <span>proposers</span>
                <span className="text-white">one strategy each</span>
              </div>
              <div className="flex justify-between gap-2">
                <span>critic</span>
                <span className="text-white">lessons for the next round</span>
              </div>
              <div className="flex justify-between gap-2">
                <span>reviewer</span>
                <span className="text-white">checks the winner</span>
              </div>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center justify-between text-on-surface-variant font-mono text-[11px]">
            <span>Token usage shown per run</span>
            <span className="text-white font-medium">LangGraph</span>
          </div>
        </div>

        {/* Card 4: guardrails */}
        <div className="bento-card rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative">
          <div>
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant">
                GUARDRAILS
              </span>
              <span className="material-symbols-outlined text-[16px] text-on-surface-variant">shield</span>
            </div>
            <h3 className="text-xl text-white font-medium">NeMo Guardrails + a policy gate</h3>
            <p className="mt-1 text-on-surface-variant text-[13px]">
              NeMo Guardrails screens what goes in and what comes out. A deterministic
              policy gate and a security scan check every candidate patch.
            </p>

            <div className="mt-5 p-3 rounded-lg bg-[#07090e] border border-outline-variant/50 space-y-2 font-mono text-[11px]">
              <div className="flex items-center gap-2 text-white">
                <span className="material-symbols-outlined text-error text-[15px]">block</span>
                <span className="font-medium truncate">#3 blocked: shell access in patch</span>
              </div>
              <div className="flex items-center gap-2 text-white">
                <span className="material-symbols-outlined text-amber-300 text-[15px]">gpp_maybe</span>
                <span className="font-medium truncate">#4 flagged: new eval() finding</span>
              </div>
              <div className="flex items-center gap-2 text-white">
                <span className="material-symbols-outlined text-primary text-[15px]">check_circle</span>
                <span className="font-medium truncate">#5 clean: policy and scan pass</span>
              </div>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center justify-between font-mono text-[11px] text-secondary">
            <span>input · policy · output</span>
            <span>shown on every run</span>
          </div>
        </div>

        {/* Card 5: human merges (wide) */}
        <div className="bento-card md:col-span-2 lg:col-span-1 rounded-xl bg-surface-container-low border border-outline-variant/60 p-6 flex flex-col justify-between shadow-lg relative">
          <div>
            <div className="flex items-center justify-between mb-4 gap-2">
              <span className="text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-surface-container-high text-primary border border-primary/20">
                HUMAN IN THE LOOP
              </span>
              <span className="font-mono text-[11px] text-white">agents cannot merge or push to main</span>
            </div>
            <h3 className="text-xl text-white font-medium">A pull request with proof, and an on-call human</h3>
            <p className="mt-1 text-on-surface-variant text-[13px] max-w-xl">
              When a fix passes every test, PatchLoop opens a GitHub pull request with the
              diff and the test output, and a Slack alert tells the on-call engineer. They
              review and merge it. Everything is also available from the CLI.
            </p>

            <div className="mt-5 p-3 rounded-lg bg-[#07090e] border border-outline-variant/50 font-mono text-[10.5px] text-on-surface-variant space-y-1 overflow-x-auto">
              <div className="whitespace-nowrap">
                <span className="text-primary">$</span> patchloop login --token plk_…
              </div>
              <div className="whitespace-nowrap">
                <span className="text-primary">$</span> patchloop fix paginate
              </div>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline-variant/40 flex items-center justify-between text-on-surface-variant font-mono text-[11px] gap-2">
            <span>GitHub pull requests · Slack alerts · CLI</span>
            <Link href="/docs/cli" className="text-primary font-medium hover:underline">
              CLI docs →
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
