"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import signinBackground from "@/public/signin-bg.png";
import signinVignette from "@/public/signin-bg-vignette.png";

const TABS = ["Password", "Magic Link", "Passkey"] as const;
type Tab = (typeof TABS)[number];

export default function SignInCard() {
  const [activeTab, setActiveTab] = useState<Tab>("Password");
  const [showPassword, setShowPassword] = useState(false);

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
              <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
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
            <header className="mb-6 space-y-3">
              <div>
                <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white">Welcome back</h1>
                <p className="text-sm text-on-surface-variant mt-1.5 leading-relaxed">
                  Sign in to your account.
                </p>
              </div>

              <nav aria-label="Sign in method tabs">
                <div className="grid grid-cols-3 p-1 rounded-xl bg-surface-container-lowest/90 border border-white/[0.08] text-xs font-medium text-on-surface-variant shadow-inner">
                  {TABS.map((tab) => (
                    <button
                      key={tab}
                      type="button"
                      aria-selected={activeTab === tab}
                      onClick={() => setActiveTab(tab)}
                      className={`py-2 rounded-lg text-center font-medium transition flex items-center justify-center gap-1.5 ${
                        activeTab === tab
                          ? "text-white bg-white/[0.08] shadow-[0_1px_3px_rgba(0,0,0,0.5)] border border-white/[0.09]"
                          : "hover:text-on-surface"
                      }`}
                    >
                      {tab === "Passkey" && (
                        <span className="material-symbols-outlined text-[14px]">key</span>
                      )}
                      <span>{tab}</span>
                    </button>
                  ))}
                </div>
              </nav>
            </header>

            {activeTab === "Password" && (
              <form className="space-y-4" onSubmit={(e) => e.preventDefault()}>
                <div className="space-y-1.5">
                  <label className="block text-xs font-medium text-on-surface" htmlFor="work-email">
                    Email
                  </label>
                  <div className="relative rounded-lg shadow-sm">
                    <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-on-surface-variant">
                      <span className="material-symbols-outlined text-[16px]">mail</span>
                    </div>
                    <input
                      autoComplete="email"
                      id="work-email"
                      required
                      type="email"
                      placeholder="you@company.com"
                      className="block w-full pl-10 pr-3.5 py-2.5 text-sm rounded-lg text-white placeholder-on-surface-variant/70 bg-surface-container-lowest/65 border border-white/[0.07] transition-all duration-200 focus:outline-none focus:border-primary/60 focus:bg-surface-container-lowest/95 focus:shadow-[0_0_0_2px_rgba(16,185,129,0.18),0_0_16px_-2px_rgba(16,185,129,0.25)] hover:border-white/[0.14]"
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-medium text-on-surface" htmlFor="password">
                      Password
                    </label>
                    <a href="#reset-password" className="text-xs text-on-surface-variant hover:text-primary transition">
                      Forgot password?
                    </a>
                  </div>
                  <div className="relative rounded-lg shadow-sm">
                    <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-on-surface-variant">
                      <span className="material-symbols-outlined text-[16px]">lock</span>
                    </div>
                    <input
                      autoComplete="current-password"
                      id="password"
                      required
                      type={showPassword ? "text" : "password"}
                      placeholder="Enter your password"
                      className="block w-full pl-10 pr-10 py-2.5 text-sm rounded-lg text-white placeholder-on-surface-variant/70 bg-surface-container-lowest/65 border border-white/[0.07] transition-all duration-200 focus:outline-none focus:border-primary/60 focus:bg-surface-container-lowest/95 focus:shadow-[0_0_0_2px_rgba(16,185,129,0.18),0_0_16px_-2px_rgba(16,185,129,0.25)] hover:border-white/[0.14]"
                    />
                    <button
                      type="button"
                      aria-label="Toggle password visibility"
                      onClick={() => setShowPassword((v) => !v)}
                      className={`absolute inset-y-0 right-0 pr-3 flex items-center transition focus:outline-none ${
                        showPassword ? "text-primary" : "text-on-surface-variant hover:text-on-surface"
                      }`}
                    >
                      <span className="material-symbols-outlined text-[16px]">
                        {showPassword ? "visibility_off" : "visibility"}
                      </span>
                    </button>
                  </div>
                </div>

                <label className="flex items-center gap-2 cursor-pointer select-none group pt-1">
                  <input
                    defaultChecked
                    type="checkbox"
                    className="w-4 h-4 rounded bg-surface-container-lowest border-white/20 text-primary focus:ring-primary/30 focus:ring-offset-0 transition cursor-pointer"
                  />
                  <span className="text-xs text-on-surface-variant group-hover:text-on-surface transition">
                    Remember this device for 30 days
                  </span>
                </label>

                <div className="pt-2">
                  <button
                    type="submit"
                    className="group relative w-full overflow-hidden rounded-xl bg-gradient-to-b from-surface-bright to-surface-container-lowest px-5 py-3 text-sm font-semibold text-white shadow-[0_0_20px_rgba(16,185,129,0.15)] border border-primary/30 hover:border-primary/60 hover:shadow-[0_0_25px_rgba(16,185,129,0.3)] transition-all duration-300 active:scale-[0.99] focus:outline-none focus:ring-2 focus:ring-primary/50"
                  >
                    <span className="absolute inset-0 w-full h-full bg-gradient-to-r from-transparent via-white/[0.07] to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-1000 ease-out" />
                    <span className="relative flex items-center justify-center gap-2 tracking-wide font-medium">
                      <span>Sign in</span>
                      <span className="material-symbols-outlined text-[16px] text-primary group-hover:translate-x-0.5 transition-transform">
                        arrow_forward
                      </span>
                    </span>
                  </button>
                </div>
              </form>
            )}

            {activeTab === "Magic Link" && (
              <form className="space-y-4" onSubmit={(e) => e.preventDefault()}>
                <div className="space-y-1.5">
                  <label className="block text-xs font-medium text-on-surface" htmlFor="magic-email">
                    Email
                  </label>
                  <div className="relative rounded-lg shadow-sm">
                    <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-on-surface-variant">
                      <span className="material-symbols-outlined text-[16px]">mail</span>
                    </div>
                    <input
                      id="magic-email"
                      type="email"
                      placeholder="you@company.com"
                      className="block w-full pl-10 pr-3.5 py-2.5 text-sm rounded-lg text-white placeholder-on-surface-variant/70 bg-surface-container-lowest/65 border border-white/[0.07] transition-all duration-200 focus:outline-none focus:border-primary/60"
                    />
                  </div>
                </div>
                <button
                  type="submit"
                  className="group relative w-full overflow-hidden rounded-xl bg-gradient-to-b from-surface-bright to-surface-container-lowest px-5 py-3 text-sm font-semibold text-white shadow-[0_0_20px_rgba(16,185,129,0.15)] border border-primary/30 hover:border-primary/60 transition-all duration-300 active:scale-[0.99] focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  <span className="relative flex items-center justify-center gap-2 tracking-wide font-medium">
                    <span>Send magic link</span>
                    <span className="material-symbols-outlined text-[16px] text-primary">arrow_forward</span>
                  </span>
                </button>
              </form>
            )}

            {activeTab === "Passkey" && (
              <div className="flex flex-col items-center gap-4 py-4 text-center">
                <div className="relative w-16 h-16 rounded-full bg-primary/10 border border-primary/40 flex items-center justify-center text-primary shadow-[0_0_15px_rgba(16,185,129,0.3)]">
                  <span className="material-symbols-outlined text-[28px]">key</span>
                </div>
                <p className="text-xs text-on-surface-variant max-w-xs">
                  Use Touch ID, Windows Hello, or a security key to sign in instantly.
                </p>
                <button
                  type="button"
                  className="w-full py-3 px-4 rounded-lg bg-primary hover:bg-primary/90 text-bg font-semibold text-sm transition-all duration-200 shadow-md flex items-center justify-center gap-2"
                >
                  <span>Continue with a passkey</span>
                </button>
              </div>
            )}

            <div className="mt-6 space-y-4">
              <div className="relative flex items-center justify-center">
                <div className="border-t border-white/[0.08] w-full" />
                <span className="absolute bg-surface-container-lowest px-3 text-[10px] font-mono tracking-widest text-on-surface-variant/70 uppercase rounded-full border border-white/[0.04]">
                  Or continue with
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2.5">
                <button
                  type="button"
                  aria-label="Continue with GitHub"
                  className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-surface-container-lowest/90 border border-white/[0.07] hover:border-white/20 hover:bg-white/[0.04] text-xs font-medium text-on-surface-variant hover:text-white transition shadow-sm"
                >
                  <svg className="w-4 h-4 fill-current text-white" viewBox="0 0 24 24">
                    <path
                      fillRule="evenodd"
                      clipRule="evenodd"
                      d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                    />
                  </svg>
                  <span>GitHub</span>
                </button>
                <button
                  type="button"
                  aria-label="Continue with Google"
                  className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-surface-container-lowest/90 border border-white/[0.07] hover:border-white/20 hover:bg-white/[0.04] text-xs font-medium text-on-surface-variant hover:text-white transition shadow-sm"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24">
                    <path d="M12 5c1.6 0 3 .6 4.1 1.7l3.1-3.1C17.3 1.8 14.8 1 12 1 7.5 1 3.7 3.6 1.9 7.3l3.7 2.9C6.5 7.4 9 5 12 5z" fill="#EA4335" />
                    <path d="M23.5 12.3c0-.8-.1-1.7-.2-2.3H12v4.6h6.5c-.3 1.5-1.1 2.8-2.4 3.7l3.7 2.9c2.2-2 3.7-5 3.7-8.9z" fill="#4285F4" />
                    <path d="M5.6 14.8c-.2-.7-.4-1.5-.4-2.3s.2-1.6.4-2.3L1.9 7.3C.7 9.7 0 12 0 14.5s.7 4.8 1.9 7.2l3.7-6.9z" fill="#FBBC05" />
                    <path d="M12 24c3.2 0 6-1.1 8-3.1l-3.7-2.9c-1.1.7-2.5 1.2-4.3 1.2-3 0-5.5-2.4-6.4-5.2L1.9 17C3.7 20.7 7.5 24 12 24z" fill="#34A853" />
                  </svg>
                  <span>Google</span>
                </button>
                <button
                  type="button"
                  className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-surface-container-lowest/90 border border-white/[0.07] hover:border-white/20 hover:bg-white/[0.04] text-xs font-medium text-on-surface-variant hover:text-white transition shadow-sm"
                >
                  <span className="material-symbols-outlined text-[16px] text-primary">dns</span>
                  <span>SSO</span>
                </button>
              </div>
            </div>

            <footer className="mt-6 pt-4 border-t border-white/[0.06] flex items-center justify-center text-xs text-on-surface-variant">
              <div className="flex items-center gap-3">
                <a href="#terms" className="hover:text-on-surface-variant transition">
                  Terms
                </a>
                <span>•</span>
                <a href="#privacy" className="hover:text-on-surface-variant transition">
                  Privacy
                </a>
              </div>
            </footer>
          </article>
        </div>
      </main>

      <footer className="relative z-20 py-4 px-6 border-t border-white/[0.04] bg-bg/60 backdrop-blur text-on-surface-variant text-[11px]">
        <div className="max-w-7xl mx-auto text-center">
          <span>© 2026 PatchLoop, Inc.</span>
        </div>
      </footer>
    </div>
  );
}
