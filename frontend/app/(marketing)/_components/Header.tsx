"use client";

import Link from "next/link";
import { useState } from "react";
import { Icon, LinkButton, Logo } from "../../_ui";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#entry-points", label: "Where you start" },
  { href: "#trust", label: "Trust" },
  { href: "#faq", label: "FAQ" },
  { href: "/docs", label: "Docs" },
];

export default function Header() {
  const [open, setOpen] = useState(false);
  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-border bg-bg/80 backdrop-blur-xl">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 lg:px-8">
        <Logo />
        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="focus-ring rounded-md px-3 py-1.5 text-[13.5px] text-on-surface-variant transition-colors hover:text-white">
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <Link href="/signin" className="focus-ring hidden rounded-md px-3 py-1.5 text-[13.5px] text-on-surface-variant hover:text-white sm:block">
            Sign in
          </Link>
          <LinkButton href="/signup" size="sm">
            Get started
          </LinkButton>
          <button
            type="button"
            className="focus-ring flex h-8 w-8 items-center justify-center rounded-md border border-border-strong text-on-surface-variant md:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <Icon name={open ? "x" : "menu"} size={16} />
          </button>
        </div>
      </div>
      {open && (
        <nav aria-label="Mobile" className="border-t border-border bg-bg px-4 py-2 md:hidden">
          {[...LINKS, { href: "/signin", label: "Sign in" }, { href: "/try", label: "Live demo" }].map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className="focus-ring block rounded-md px-2 py-2.5 text-[15px] text-on-surface-variant hover:text-white">
              {l.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}
