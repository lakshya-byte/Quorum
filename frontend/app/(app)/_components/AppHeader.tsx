"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "../../_lib/auth";

const NAV = [
  { href: "/try", label: "Try it", auth: false },
  { href: "/dashboard", label: "Dashboard", auth: true },
  { href: "/settings/tokens", label: "API tokens", auth: true },
  { href: "/docs", label: "Docs", auth: false },
];

export default function AppHeader() {
  const { user, loading, signOut } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const items = NAV.filter((n) => !n.auth || user);

  return (
    <header className="sticky top-0 z-30 w-full bg-[#07090e]/90 backdrop-blur-xl border-b border-outline-variant/50">
      <div className="h-14 max-w-7xl mx-auto px-4 lg:px-8 flex items-center justify-between gap-3">
        <div className="flex items-center gap-5 min-w-0">
          <Link href="/" className="flex items-center gap-2.5 group shrink-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img alt="" src="/patchloop-logo.svg" className="h-7 w-7 transition-transform group-hover:scale-105" />
            <span className="text-[15px] text-white tracking-tight font-semibold">PatchLoop</span>
          </Link>
          <nav className="hidden md:flex items-center gap-1">
            {items.map((n) => {
              const active = pathname === n.href || (n.href !== "/docs" && pathname?.startsWith(n.href + "/"));
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  className={`px-3 py-1 rounded text-[13px] transition-colors ${
                    active ? "text-white bg-surface-container-high" : "text-on-surface-variant hover:text-white hover:bg-surface-container-high"
                  }`}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-2">
          {loading ? (
            <span className="w-24 h-7 rounded bg-surface-container-low animate-pulse" />
          ) : user ? (
            <>
              <span className="hidden sm:inline font-mono text-[11px] text-on-surface-variant max-w-[160px] truncate" title={user.companyName}>
                {user.companyName}
              </span>
              <button
                onClick={signOut}
                className="hidden md:inline-flex items-center gap-1 px-3 py-1.5 rounded border border-outline-variant/60 text-[12.5px] text-on-surface-variant hover:text-white hover:bg-surface-container-high"
              >
                <span className="material-symbols-outlined text-[15px]">logout</span>
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link href="/signin" className="hidden sm:inline text-[13px] text-on-surface-variant hover:text-white">
                Sign in
              </Link>
              <Link
                href="/signup"
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-primary text-black text-[12.5px] font-semibold hover:bg-[#34d399]"
              >
                Get started
              </Link>
            </>
          )}
          <button
            className="md:hidden w-9 h-9 rounded-lg border border-outline-variant/60 text-on-surface-variant flex items-center justify-center"
            onClick={() => setOpen((v) => !v)}
            aria-label="Menu"
            aria-expanded={open}
          >
            <span className="material-symbols-outlined text-[20px]">{open ? "close" : "menu"}</span>
          </button>
        </div>
      </div>
      {open && (
        <nav className="md:hidden border-t border-outline-variant/40 px-4 py-2 flex flex-col">
          {items.map((n) => (
            <Link key={n.href} href={n.href} onClick={() => setOpen(false)} className="py-2 text-[14px] text-on-surface-variant hover:text-white">
              {n.label}
            </Link>
          ))}
          {user && (
            <button onClick={signOut} className="py-2 text-left text-[14px] text-on-surface-variant hover:text-white">
              Sign out
            </button>
          )}
        </nav>
      )}
    </header>
  );
}
