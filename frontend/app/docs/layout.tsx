import Link from "next/link";
import DocsSidebar from "./_components/DocsSidebar";

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen w-full flex flex-col">
      <header className="w-full border-b border-outline-variant/50 bg-bg/80 backdrop-blur-md sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-4 lg:px-8 h-14 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5 group">
            <img
              src="/patchloop-logo.svg"
              alt=""
              className="h-6 w-6 transition-transform group-hover:scale-105"
            />
            <span className="text-[15px] text-white tracking-tight font-semibold">
              PatchLoop
            </span>
            <span className="text-[10px] uppercase font-mono tracking-widest px-1.5 py-0.5 rounded bg-surface-container-high text-primary border border-primary/25">
              Docs
            </span>
          </Link>
          <Link
            href="/"
            className="flex items-center gap-1.5 text-[13px] text-on-surface-variant hover:text-white transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">arrow_back</span>
            <span>Back to site</span>
          </Link>
        </div>
      </header>

      <div className="flex-1 w-full max-w-6xl mx-auto px-4 lg:px-8 py-10 flex flex-col md:flex-row gap-10">
        <aside className="md:w-56 shrink-0">
          <div className="md:sticky md:top-24">
            <DocsSidebar />
          </div>
        </aside>

        <main className="flex-1 min-w-0 max-w-3xl">{children}</main>
      </div>
    </div>
  );
}
