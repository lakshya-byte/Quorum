import Link from "next/link";
import { Logo } from "../../_ui";

const COLS = [
  {
    title: "Product",
    links: [
      { href: "/try", label: "Live demo" },
      { href: "/signup", label: "Create account" },
      { href: "/signin", label: "Sign in" },
    ],
  },
  {
    title: "Docs",
    links: [
      { href: "/docs/getting-started", label: "Getting started" },
      { href: "/docs/cli", label: "CLI" },
      { href: "/docs/api-reference", label: "API reference" },
    ],
  },
  {
    title: "Project",
    links: [
      { href: "#trust", label: "How we keep it safe" },
      { href: "#faq", label: "FAQ" },
      { href: "/docs/backend", label: "Architecture" },
    ],
  },
];

export default function Footer() {
  return (
    <footer className="border-t border-border bg-[#05070a]">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 lg:grid-cols-[1.4fr_2fr] lg:px-8">
        <div className="flex flex-col gap-3">
          <Logo />
          <p className="max-w-xs text-[13.5px] leading-6 text-on-surface-variant">Agents propose. Your tests decide. You merge. A hackathon project, built in the open.</p>
        </div>
        <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
          {COLS.map((c) => (
            <nav key={c.title} aria-label={c.title}>
              <h3 className="text-[12px] font-medium uppercase tracking-wider text-text-subtle">{c.title}</h3>
              <ul className="mt-3 flex flex-col gap-2">
                {c.links.map((l) => (
                  <li key={l.label}>
                    <Link href={l.href} className="focus-ring rounded text-[13.5px] text-on-surface-variant hover:text-white">
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
      </div>
      <div className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-5 text-[12.5px] text-text-subtle sm:flex-row sm:justify-between lg:px-8">
          <span>&copy; 2026 PatchLoop. Hackathon project.</span>
          <span>Models and sandboxes run on Nebius. Not affiliated with GitHub or Slack.</span>
        </div>
      </div>
    </footer>
  );
}
