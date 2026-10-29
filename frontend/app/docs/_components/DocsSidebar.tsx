"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/docs", label: "Overview" },
  { href: "/docs/getting-started", label: "Getting started" },
  { href: "/docs/cli", label: "CLI" },
  { href: "/docs/frontend", label: "Frontend" },
  { href: "/docs/backend", label: "Backend" },
  { href: "/docs/api-reference", label: "API reference" },
];

export default function DocsSidebar() {
  const pathname = usePathname();

  return (
    <nav className="space-y-1">
      {LINKS.map((link) => {
        const active = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            className={`block px-3 py-1.5 rounded-md text-[13px] transition-colors ${
              active
                ? "bg-primary/10 text-primary font-medium border border-primary/20"
                : "text-on-surface-variant hover:text-white hover:bg-surface-container-low border border-transparent"
            }`}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
