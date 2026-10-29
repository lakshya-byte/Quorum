"use client";

import { Icon } from "../../_ui";
import Image from "next/image";
import Link from "next/link";
import signupBackground from "@/public/signup-bg.png";
import { SignUpForm } from "./AuthForms";

export default function SignUpCard() {
  return (
    <div className="relative min-h-screen w-full overflow-hidden flex flex-col">
      {/* Ambient backdrop */}
      <div aria-hidden className="fixed inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute inset-0 opacity-30 mix-blend-screen scale-105">
          <Image
            src={signupBackground}
            alt=""
            fill
            priority
            placeholder="blur"
            sizes="100vw"
            className="object-cover object-center saturate-150 contrast-125"
          />
        </div>
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(to top, var(--bg) 0%, rgba(7,9,14,0.8) 60%, rgba(7,9,14,0.9) 100%)",
          }}
        />
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse at top, rgba(16,185,129,0.1) 0%, transparent 60%)",
          }}
        />
        <div
          className="absolute inset-0 opacity-40"
          style={{
            backgroundSize: "40px 40px",
            backgroundImage:
              "linear-gradient(to right, rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,0.03) 1px, transparent 1px)",
          }}
        />
      </div>

      <div className="relative z-10 min-h-screen flex flex-col justify-between items-center px-4 sm:px-6 lg:px-8 py-6">
        {/* Top bar */}
        <header className="w-full max-w-6xl mx-auto flex items-center justify-between py-2 border-b border-white/[0.06]">
          <Link
            href="/"
            aria-label="PatchLoop Home"
            className="flex items-center gap-2.5 group focus:outline-none focus:ring-1 focus:ring-primary/50 rounded-lg p-1"
          >
            <img
              src="/patchloop-logo.svg"
              alt=""
              className="w-7 h-7 rounded-md transition-transform group-hover:scale-105"
            />
            <span className="font-semibold tracking-tight text-white text-base">PatchLoop</span>
          </Link>

          <div className="flex items-center text-xs text-on-surface-variant">
            <span className="hidden sm:inline">Already have an account?</span>
            <Link
              href="/signin"
              className="flex items-center gap-1 text-primary hover:text-primary/80 font-medium ml-1.5 transition-colors"
            >
              <span>Sign in</span>
              <Icon name="arrow-right" size={14} />
            </Link>
          </div>
        </header>

        {/* Card */}
        <main className="w-full max-w-xl mx-auto my-auto py-8">
          <section
            className="relative rounded-2xl bg-surface-container-lowest/90 backdrop-blur-2xl p-6 sm:p-8 border border-white/[0.07]"
            style={{
              boxShadow:
                "inset 0 1px 0 rgba(255,255,255,0.1), 0 25px 50px -12px rgba(0,0,0,0.85)",
            }}
          >
            <div className="absolute -top-[1px] left-1/2 -translate-x-1/2 w-48 h-[2px] bg-gradient-to-r from-transparent via-primary to-transparent" />

            <div className="text-center mb-7">
              <h1 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">Create your account</h1>
              <p className="mt-2 text-sm text-on-surface-variant max-w-sm mx-auto leading-relaxed">
                Fixes are proposed by agents, proven by tests in isolated sandboxes, and merged by you.
              </p>
            </div>

            <SignUpForm />

            <p className="mt-5 text-center text-[11px] text-on-surface-variant/70 leading-relaxed">
              By creating an account, you agree to our{" "}
              <a href="#terms" className="underline hover:text-on-surface-variant transition">
                Terms
              </a>{" "}
              and{" "}
              <a href="#privacy" className="underline hover:text-on-surface-variant transition">
                Privacy Policy
              </a>
              .
            </p>
          </section>

          <p className="mt-6 text-center text-[12px] text-on-surface-variant">
            Just looking?{" "}
            <Link href="/try" className="text-primary hover:text-primary/80">
              Try the live demo without an account
            </Link>
          </p>
        </main>

        <footer className="w-full max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between py-4 text-xs text-on-surface-variant border-t border-white/[0.06] gap-2">
          <span>© 2026 PatchLoop, Inc.</span>
          <div className="flex items-center gap-4">
            <a href="#privacy" className="hover:text-on-surface-variant transition">
              Privacy
            </a>
            <a href="#terms" className="hover:text-on-surface-variant transition">
              Terms
            </a>
          </div>
        </footer>
      </div>
    </div>
  );
}
