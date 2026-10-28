import Link from "next/link";

export default function Header() {
  return (
    <header className="fixed top-0 w-full z-50 bg-[#07090e]/85 backdrop-blur-xl border-b border-outline-variant/50">
      <div className="h-14 max-w-7xl mx-auto px-4 lg:px-8 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <a className="flex items-center gap-2.5 group" href="#">
            <img
              alt="PatchLoop"
              src="/patchloop-logo.svg"
              className="h-7 w-7 object-contain transition-transform duration-200 group-hover:scale-105"
            />
            <span className="text-[16px] text-white tracking-tight font-semibold">
              PatchLoop
            </span>
          </a>
          <div className="hidden sm:flex items-center gap-2 ml-1">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-container-high text-primary border border-primary/25 flex items-center gap-1.5 tracking-wide">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              Engine v2.4 Hermetic
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-container-low text-on-surface-variant/80 border border-outline-variant/40 flex items-center gap-1 tracking-wide">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              All Systems Operational
            </span>
          </div>
        </div>

        <nav className="hidden md:flex items-center gap-1">
          <a
            className="px-3 py-1 rounded text-on-surface-variant hover:text-white hover:bg-surface-container-high transition-colors text-[13px]"
            href="#prover-dashboard"
          >
            Core Loop
          </a>
          <a
            className="px-3 py-1 rounded text-on-surface-variant hover:text-white hover:bg-surface-container-high transition-colors text-[13px]"
            href="#proof-explorer"
          >
            Telemetry
          </a>
          <a
            className="px-3 py-1 rounded text-on-surface-variant hover:text-white hover:bg-surface-container-high transition-colors text-[13px]"
            href="#architecture"
          >
            Architecture
          </a>
          <a
            className="px-3 py-1 rounded text-on-surface-variant hover:text-white hover:bg-surface-container-high transition-colors text-[13px]"
            href="#benchmarks"
          >
            Benchmarks
          </a>
          <Link
            className="px-3 py-1 rounded text-on-surface-variant hover:text-white hover:bg-surface-container-high transition-colors text-[13px]"
            href="/docs"
          >
            Docs
          </Link>
        </nav>

        <div className="flex items-center gap-3">
          <Link
            className="hidden sm:inline-flex text-on-surface-variant hover:text-white transition-colors text-[13px] font-medium"
            href="/signin"
          >
            Sign in
          </Link>
          <Link
            className="relative inline-flex items-center justify-center gap-1.5 px-3.5 py-1.5 rounded bg-primary text-black text-[13px] font-semibold shadow-[0_0_16px_rgba(16,185,129,0.35)] hover:bg-[#34d399] transition-all duration-150"
            href="/signup"
          >
            <span>Get Started</span>
            <span className="material-symbols-outlined text-[15px]">arrow_forward</span>
          </Link>
        </div>
      </div>
    </header>
  );
}
