import Link from "next/link";

export default function Footer() {
  return (
    <footer className="w-full bg-[#05070a] border-t border-outline-variant/40 py-6">
      <div className="max-w-7xl mx-auto px-4 lg:px-8 flex flex-col md:flex-row items-center justify-between gap-4 font-mono text-[12px] text-on-surface-variant">
        <div className="flex items-center gap-3 flex-wrap justify-center">
          <span className="text-[12px] text-on-surface-variant">
            Powered by Nemotron &amp; Nebius Token Factory
          </span>
        </div>
        <div className="flex items-center gap-4 flex-wrap justify-center">
          <span className="text-[12px] text-on-surface-variant">
            &copy; 2026 PatchLoop. Hackathon project.
          </span>
          <Link className="text-[12px] text-on-surface-variant hover:text-white transition-colors" href="/try">
            Live demo
          </Link>
          <Link className="text-[12px] text-on-surface-variant hover:text-white transition-colors" href="/docs/api-reference">
            API reference
          </Link>
        </div>
      </div>
    </footer>
  );
}
