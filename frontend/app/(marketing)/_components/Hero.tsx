"use client";

import { useRef } from "react";
import Link from "next/link";
import Image from "next/image";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import ProverDashboard from "./ProverDashboard";
import heroBackground from "@/public/landing_hero_background.png";

gsap.registerPlugin(useGSAP, ScrollTrigger);

export default function Hero() {
  const rootRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      gsap.fromTo(
        imageRef.current,
        { opacity: 0, scale: 1.06 },
        { opacity: 1, scale: 1, duration: 1.4, ease: "power2.out" }
      );

      gsap.to(imageRef.current, {
        yPercent: 10,
        ease: "none",
        scrollTrigger: {
          trigger: rootRef.current,
          start: "top top",
          end: "bottom top",
          scrub: true,
        },
      });

      const tl = gsap.timeline({ delay: 0.1 });

      tl.fromTo(
        ".hero-pill",
        { opacity: 0, y: -8 },
        { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }
      )
        .fromTo(
          ".hero-headline",
          { opacity: 0, y: 18 },
          { opacity: 1, y: 0, duration: 0.7, ease: "power3.out" },
          "-=0.25"
        )
        .fromTo(
          ".hero-sub",
          { opacity: 0, y: 14 },
          { opacity: 1, y: 0, duration: 0.6, ease: "power2.out" },
          "-=0.4"
        )
        .fromTo(
          ".hero-cta",
          { opacity: 0, y: 10 },
          { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" },
          "-=0.35"
        )
        .fromTo(
          ".hero-dashboard",
          { opacity: 0, y: 32, scale: 0.98 },
          { opacity: 1, y: 0, scale: 1, duration: 0.8, ease: "power3.out" },
          "-=0.25"
        );
    },
    { scope: rootRef }
  );

  return (
    <div ref={rootRef} className="relative w-full overflow-hidden">
      {/* Hero background image */}
      <div
        ref={imageRef}
        aria-hidden
        className="absolute inset-x-0 top-0 h-[820px] pointer-events-none"
        style={{
          maskImage:
            "linear-gradient(to bottom, black 0%, black 45%, transparent 92%)",
          WebkitMaskImage:
            "linear-gradient(to bottom, black 0%, black 45%, transparent 92%)",
        }}
      >
        <Image
          src={heroBackground}
          alt=""
          fill
          priority
          placeholder="blur"
          sizes="100vw"
          className="object-cover object-top opacity-60 mix-blend-screen"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-[#07090e]/20 via-[#07090e]/50 to-[#07090e]" />
      </div>

      {/* Ambient glows */}
      <div
        aria-hidden
        className="absolute -top-40 left-1/2 -translate-x-1/2 w-[880px] h-[520px] bg-gradient-to-b from-primary/15 via-secondary/10 to-transparent blur-[140px] pointer-events-none rounded-full"
      />
      <div
        aria-hidden
        className="absolute top-[640px] -left-48 w-[480px] h-[480px] bg-primary/10 blur-[130px] pointer-events-none rounded-full"
      />
      <div
        aria-hidden
        className="absolute top-[1020px] -right-48 w-[560px] h-[560px] bg-secondary/10 blur-[140px] pointer-events-none rounded-full"
      />

      <section className="relative w-full max-w-7xl mx-auto px-4 lg:px-8 pt-14 pb-16 lg:pt-20 lg:pb-20 flex flex-col items-center text-center">
        <div className="hero-pill inline-flex items-center gap-2.5 px-3.5 py-1.5 rounded-full bg-surface-container-low border border-outline-variant/60 shadow-lg shadow-black/40">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          <code className="font-mono text-[11px] text-on-surface-variant flex items-center gap-1.5">
            <span className="text-primary font-semibold">$</span> patchloop fix paginate
            <span className="inline-block w-1.5 h-3 bg-primary animate-pulse ml-0.5" />
          </code>
        </div>

        <h1 className="hero-headline mt-7 max-w-4xl text-3xl sm:text-5xl lg:text-[56px] lg:leading-[62px] text-white tracking-tight font-semibold">
          Don&apos;t suggest code fixes.
          <br className="hidden sm:inline" />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-white via-primary to-secondary">
            Prove them with tests.
          </span>
        </h1>

        <p className="hero-sub mt-5 max-w-2xl text-[16px] leading-relaxed text-on-surface-variant">
          A team of AI agents proposes fixes in parallel, each in its own isolated
          Nebius Sandbox. The tests decide which fix is good, never the AI. Guardrails
          and a policy gate check every step, a pull request opens with the proof,
          and a human reviews and merges it.
        </p>

        <div className="hero-cta mt-8 flex flex-col sm:flex-row items-center gap-3">
          <Link
            href="/try"
            className="group relative inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg bg-primary text-black text-[14px] font-semibold shadow-[0_0_24px_rgba(16,185,129,0.35)] hover:bg-[#34d399] transition-all duration-200"
          >
            <span className="material-symbols-outlined text-[18px]">play_arrow</span>
            <span>Try the live demo</span>
            <span className="material-symbols-outlined text-[16px] transition-transform duration-200 group-hover:translate-x-1">
              arrow_forward
            </span>
          </Link>
          <Link
            href="/docs/getting-started"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-surface-container-low/70 border border-outline-variant/40 text-on-surface-variant hover:text-white text-[13px]"
          >
            <span className="material-symbols-outlined text-[16px]">menu_book</span>
            <span>How it works</span>
          </Link>
        </div>

        <div className="hero-dashboard w-full flex justify-center">
          <ProverDashboard />
        </div>
      </section>
    </div>
  );
}
