export default function Footer() {
  return (
    <footer className="w-full bg-[#05070a] border-t border-outline-variant/40 py-6">
      <div className="max-w-7xl mx-auto px-4 lg:px-8 flex flex-col md:flex-row items-center justify-between gap-4 font-mono text-[12px] text-on-surface-variant">
        <div className="flex items-center gap-3 flex-wrap justify-center">
          <div className="flex items-center gap-1.5 text-primary">
            <span className="w-2 h-2 rounded-full bg-primary shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
            <span className="text-[10px] uppercase tracking-wider text-white">
              All systems operational
            </span>
          </div>
          <span className="text-outline">&bull;</span>
          <div className="flex items-center gap-1 text-on-surface-variant">
            <span className="material-symbols-outlined text-[14px]">commit</span>
            <span className="text-[11px] text-secondary">c84fa29</span>
          </div>
          <span className="text-outline">&bull;</span>
          <span className="text-[12px] text-on-surface-variant">
            Powered by Nemotron &amp; Nebius Token Factory
          </span>
        </div>
        <div className="flex items-center gap-4 flex-wrap justify-center">
          <span className="text-[12px] text-on-surface-variant">
            &copy; 2026 PatchLoop Autonomous Labs.
          </span>
          <a className="text-[12px] text-on-surface-variant hover:text-white transition-colors" href="#">
            GitHub
          </a>
          <a className="text-[12px] text-on-surface-variant hover:text-white transition-colors" href="#">
            API Spec
          </a>
          <a className="text-[12px] text-on-surface-variant hover:text-white transition-colors" href="#">
            Status
          </a>
        </div>
      </div>
    </footer>
  );
}
