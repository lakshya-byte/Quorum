"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "../../_lib/auth";
import { Icon, LinkButton, Logo, cx, type IconName } from "../../_ui";
import NotificationsBell from "./NotificationsBell";
import CommandPalette from "./CommandPalette";

type NavItem = { href: string; label: string; icon: IconName; match?: (p: string) => boolean };

const APP_NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: "home", match: (p) => p === "/dashboard" || p.startsWith("/runs") },
  { href: "/new", label: "New task", icon: "bug" },
  { href: "/integrations", label: "Integrations", icon: "plug" },
  { href: "/settings/tokens", label: "API tokens", icon: "key" },
];
const MORE_NAV: NavItem[] = [
  { href: "/try", label: "Live demo", icon: "play" },
  { href: "/docs", label: "Docs", icon: "book" },
];

function NavLink({ item, pathname, onNavigate }: { item: NavItem; pathname: string; onNavigate?: () => void }) {
  const active = item.match ? item.match(pathname) : pathname === item.href || pathname.startsWith(item.href + "/");
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cx(
        "focus-ring group flex items-center gap-2.5 rounded-lg px-3 h-9 text-[13.5px] font-medium transition-colors",
        active ? "bg-primary/10 text-white" : "text-on-surface-variant hover:bg-surface-container-high hover:text-white"
      )}
    >
      <Icon name={item.icon} size={17} className={active ? "text-primary" : "text-text-subtle group-hover:text-on-surface"} />
      {item.label}
    </Link>
  );
}

function SidebarContent({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  const { user, signOut } = useAuth();
  return (
    <div className="flex h-full flex-col gap-6 p-4">
      <div className="px-1 pt-1">
        <Logo />
      </div>
      <nav aria-label="Main" className="flex flex-col gap-1">
        {APP_NAV.map((n) => (
          <NavLink key={n.href} item={n} pathname={pathname} onNavigate={onNavigate} />
        ))}
      </nav>
      <nav aria-label="Resources" className="flex flex-col gap-1">
        <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-wider text-text-subtle">Resources</div>
        {MORE_NAV.map((n) => (
          <NavLink key={n.href} item={n} pathname={pathname} onNavigate={onNavigate} />
        ))}
      </nav>
      <div className="mt-auto rounded-lg border border-border bg-surface-container-low p-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/15 text-[13px] font-semibold text-primary">
            {(user?.companyName || user?.email || "?").slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0">
            <div className="truncate text-[13px] font-medium text-white">{user?.companyName}</div>
            <div className="truncate text-[12px] text-on-surface-variant">{user?.email}</div>
          </div>
        </div>
        <button
          onClick={signOut}
          className="focus-ring mt-3 flex h-8 w-full items-center justify-center gap-1.5 rounded-md border border-border-strong text-[13px] text-on-surface-variant hover:bg-surface-container-high hover:text-white"
        >
          <Icon name="logout" size={15} />
          Sign out
        </button>
      </div>
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname() || "";
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Guests (and the brief moment before the session check resolves) get a plain top bar.
  if (!user) {
    return (
      <div className="flex min-h-screen flex-col">
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <header className="sticky top-0 z-30 border-b border-border bg-bg/85 backdrop-blur-xl">
          <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4 lg:px-8">
            <Logo />
            <nav aria-label="Main" className="flex items-center gap-1 sm:gap-2">
              <Link href="/docs" className="focus-ring hidden rounded-md px-3 py-1.5 text-[13.5px] text-on-surface-variant hover:text-white sm:block">
                Docs
              </Link>
              {!loading && (
                <>
                  <Link href="/signin" className="focus-ring rounded-md px-3 py-1.5 text-[13.5px] text-on-surface-variant hover:text-white">
                    Sign in
                  </Link>
                  <LinkButton href="/signup" size="sm">
                    Get started
                  </LinkButton>
                </>
              )}
            </nav>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 lg:px-8">
          {children}
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen border-r border-border bg-panel lg:block">
        <SidebarContent pathname={pathname} />
      </aside>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[280px] max-w-[85vw] border-r border-border bg-panel shadow-pop">
            <SidebarContent pathname={pathname} onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}

      <CommandPalette />
      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-border bg-bg/85 px-4 backdrop-blur-xl lg:px-8">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label="Open navigation"
              className="focus-ring flex h-9 w-9 items-center justify-center rounded-lg border border-border-strong text-on-surface-variant hover:text-white lg:hidden"
            >
              <Icon name="menu" size={18} />
            </button>
            <div className="lg:hidden">
              <Logo />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event("patchloop:palette"))}
              className="focus-ring hidden h-8 items-center gap-2 rounded-md border border-border-strong px-2.5 text-[13px] text-on-surface-variant hover:text-white sm:flex"
              aria-label="Open command palette"
            >
              <Icon name="search" size={14} />
              Search
              <kbd className="rounded border border-border-strong px-1 font-mono text-[11px] text-text-subtle">Ctrl K</kbd>
            </button>
            <LinkButton href="/new" size="sm" icon="plus">
              <span className="hidden sm:inline">New task</span>
              <span className="sm:hidden">New</span>
            </LinkButton>
            <NotificationsBell />
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:py-8 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
