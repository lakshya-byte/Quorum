"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import signupBackground from "@/public/signup-bg.png";

export default function SignUpCard() {
  const [passkeyFlash, setPasskeyFlash] = useState(false);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.code === "Space" && target?.tagName !== "INPUT") {
        event.preventDefault();
        setPasskeyFlash(true);
        window.setTimeout(() => setPasskeyFlash(false), 150);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

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
              <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
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
                Start proving your fixes in an isolated sandbox — free while in beta.
              </p>
            </div>

            {/* Passkey */}
            <div className="relative group p-5 rounded-xl bg-gradient-to-b from-surface-container-low to-surface-container border border-primary/30 shadow-[0_0_35px_-5px_rgba(16,185,129,0.25)] hover:border-primary/50 transition-all duration-300 text-center">
              <div className="relative w-16 h-16 mx-auto flex items-center justify-center mb-3">
                <div className="absolute inset-0 rounded-full border border-primary/20 animate-radar-slow" />
                <div className="absolute -inset-2 rounded-full border border-primary/10 animate-radar-fast" />
                <div className="relative w-12 h-12 rounded-full bg-primary/10 border border-primary/40 flex items-center justify-center text-primary shadow-[0_0_15px_rgba(16,185,129,0.3)] group-hover:scale-105 transition-transform duration-300">
                  <span className="material-symbols-outlined text-[24px]">fingerprint</span>
                </div>
              </div>
              <button
                type="button"
                id="passkey-trigger-btn"
                className={`w-full py-3 px-4 rounded-lg text-bg font-semibold text-sm transition-all duration-150 shadow-md flex items-center justify-center gap-2 group-active:scale-[0.99] focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-surface-container ${
                  passkeyFlash ? "scale-[0.98] bg-primary/70" : "bg-primary hover:bg-primary/90"
                }`}
              >
                <span>Continue with a passkey</span>
              </button>
              <p className="mt-2.5 text-[11px] text-on-surface-variant">
                Touch ID, Windows Hello, or a security key
              </p>
            </div>

            <div className="relative my-6 text-center">
              <div aria-hidden className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-white/10" />
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="bg-surface-container-lowest px-3 font-mono uppercase tracking-widest text-[11px] text-on-surface-variant/70">
                  or
                </span>
              </div>
            </div>

            <form className="space-y-4" onSubmit={(e) => e.preventDefault()}>
              <div>
                <label className="block text-xs font-medium text-on-surface mb-1.5" htmlFor="corporate-email">
                  Work email
                </label>
                <input
                  id="corporate-email"
                  type="email"
                  placeholder="you@company.com"
                  className="w-full px-3.5 py-2.5 bg-surface-container-low border border-white/10 rounded-lg text-sm text-on-surface placeholder-on-surface-variant/60 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-on-surface mb-1.5" htmlFor="org-name">
                  Company name
                </label>
                <input
                  id="org-name"
                  type="text"
                  placeholder="Your company"
                  className="w-full px-3.5 py-2.5 bg-surface-container-low border border-white/10 rounded-lg text-sm text-on-surface placeholder-on-surface-variant/60 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition"
                />
              </div>

              <button
                type="submit"
                className="w-full py-2.5 px-4 rounded-lg bg-surface-bright hover:bg-outline border border-white/10 text-white font-medium text-sm transition duration-150 flex items-center justify-center gap-2 focus:outline-none focus:ring-2 focus:ring-white/20 shadow-sm"
              >
                <span>Create account</span>
                <span className="material-symbols-outlined text-[16px] text-primary">arrow_forward</span>
              </button>
            </form>

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

          <div className="mt-6 flex items-center justify-center gap-1.5 text-[11px] font-mono text-on-surface-variant">
            <span className="w-1.5 h-1.5 rounded-full bg-primary" />
            <span>SOC 2 Type II certified</span>
          </div>
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
