"use client";

import { Icon } from "../../_ui";
import Image from "next/image";
import Link from "next/link";
import signinBackground from "@/public/signin-bg.png";
import signinVignette from "@/public/signin-bg-vignette.png";
import { SignInForm } from "./AuthForms";


export default function SignInCard() {

  return (
    <div className="relative min-h-screen w-full overflow-hidden flex flex-col">
      {/* Ambient backdrop layers */}
      <div aria-hidden className="fixed inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute inset-0 opacity-40 mix-blend-luminosity scale-105 blur-[0.5px]">
          <Image
            src={signinBackground}
            alt=""
            fill
            priority
            placeholder="blur"
            sizes="100vw"
            className="object-cover object-center"
          />
        </div>
        <div className="absolute inset-0 opacity-25 mix-blend-screen">
          <Image
            src={signinVignette}
            alt=""
            fill
            placeholder="blur"
            sizes="100vw"
            className="object-cover object-right opacity-30 blur-2xl"
          />
        </div>
        <div
          className="absolute inset-0 opacity-70"
          style={{
            backgroundSize: "32px 32px",
            backgroundImage:
              "radial-gradient(circle, rgba(255,255,255,0.055) 1px, transparent 1px)",
          }}
        />
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse at center, rgba(7,9,14,0.3) 0%, rgba(5,7,11,0.85) 65%, rgba(3,4,7,0.98) 100%)",
          }}
        />
        <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-[700px] h-[340px] bg-primary/10 rounded-full blur-3xl" />
      </div>

      {/* Top navigation */}
      <header className="relative z-20 w-full px-6 py-5 border-b border-white/[0.06] bg-bg/40 backdrop-blur-md">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <Link
            href="/"
            className="flex items-center gap-3 group focus:outline-none focus:ring-1 focus:ring-primary/50 rounded-lg p-1 transition"
          >
            <div className="relative w-8 h-8 rounded-lg bg-surface-container-lowest border border-primary/30 flex items-center justify-center shadow-[0_0_12px_rgba(16,185,129,0.25)] group-hover:border-primary/60 transition-all">
              <img src="/patchloop-logo.svg" alt="" className="w-5 h-5" />
            </div>
            <span className="font-semibold text-lg tracking-tight text-white">PatchLoop</span>
          </Link>

          <div className="flex items-center text-xs text-on-surface-variant">
            <span className="hidden sm:inline">Don&apos;t have an account?</span>
            <Link
              href="/signup"
              className="flex items-center gap-1 text-primary hover:text-primary/80 font-medium ml-1.5 transition-colors"
            >
              <span>Sign up</span>
              <Icon name="arrow-right" size={14} />
            </Link>
          </div>
        </div>
      </header>

      {/* Auth card */}
      <main className="relative z-10 flex-1 flex items-center justify-center p-4 sm:p-6 my-6">
        <div className="relative w-full max-w-[440px]">
          <div
            aria-hidden
            className="absolute top-[38%] -left-[20%] w-[140%] h-7 -rotate-[14deg] blur-[8px] mix-blend-screen opacity-75 pointer-events-none animate-[caustic-pulse_10s_ease-in-out_infinite_alternate]"
            style={{
              background:
                "linear-gradient(90deg, transparent 0%, rgba(56,189,248,0) 10%, rgba(34,211,238,0.25) 25%, rgba(52,211,153,0.6) 42%, rgba(250,204,21,0.75) 55%, rgba(244,63,94,0.7) 68%, rgba(168,85,247,0.4) 82%, transparent 100%)",
            }}
          />
          <div
            aria-hidden
            className="absolute top-[39%] -left-[25%] w-[150%] h-1.5 -rotate-[14deg] blur-[1.5px] mix-blend-screen opacity-85 pointer-events-none"
            style={{
              background:
                "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.95) 45%, rgba(254,240,138,0.95) 54%, rgba(251,113,133,0.9) 65%, transparent 95%)",
            }}
          />
          <div className="absolute -inset-1 rounded-3xl bg-gradient-to-b from-primary/20 via-transparent to-secondary/10 blur-xl opacity-60 pointer-events-none" />

          <article
            className="relative rounded-2xl p-7 sm:p-9 overflow-hidden border border-white/[0.085]"
            style={{
              background:
                "linear-gradient(145deg, rgba(14,18,27,0.82) 0%, rgba(7,9,14,0.88) 100%)",
              backdropFilter: "blur(28px)",
              WebkitBackdropFilter: "blur(28px)",
              boxShadow:
                "0 0 0 1px rgba(0,0,0,0.8), 0 24px 60px -12px rgba(0,0,0,0.75), 0 0 80px -20px rgba(16,185,129,0.12), inset 0 1px 1px 0 rgba(255,255,255,0.12)",
            }}
          >
            <header className="mb-6">
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white">Welcome back</h1>
              <p className="text-sm text-on-surface-variant mt-1.5 leading-relaxed">
                Sign in to start fixes, open pull requests and manage API tokens.
              </p>
            </header>

            <SignInForm />

            <p className="mt-5 text-center text-[12px] text-on-surface-variant">
              Just looking?{" "}
              <Link href="/try" className="text-primary hover:text-primary/80">
                Try the live demo without an account
              </Link>
            </p>

          </article>
        </div>
      </main>

      <footer className="relative z-20 py-4 px-6 border-t border-white/[0.04] bg-bg/60 backdrop-blur text-on-surface-variant text-[11px]">
        <div className="max-w-7xl mx-auto text-center">
          <span>© 2026 PatchLoop. Hackathon project.</span>
        </div>
      </footer>
    </div>
  );
}
