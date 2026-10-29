const STATS = [
  { label: "Every attempt runs in", value: "Its own sandbox", icon: "deployed_code", color: "text-primary" },
  { label: "What decides a fix", value: "The tests", icon: "fact_check", color: "text-secondary" },
  { label: "Checks on every run", value: "Guardrails + policy", icon: "security", color: "text-primary" },
  { label: "Who merges", value: "A human", icon: "person_check", color: "text-secondary" },
];

export default function CredibilityStrip() {
  return (
    <section
      id="benchmarks"
      className="w-full bg-[#090c12] border-y border-outline-variant/50 py-8 scroll-mt-14"
    >
      <div className="max-w-7xl mx-auto px-4 lg:px-8 flex flex-col gap-6">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-on-surface-variant">
            <span className="material-symbols-outlined text-[16px] text-primary">memory</span>
            <span>
              ISOLATED NEBIUS SANDBOXES &bull; NEMOTRON MODELS VIA NEBIUS TOKEN FACTORY
              &bull; LANGGRAPH AGENT TEAM
            </span>
          </div>
          <span className="font-mono text-[11px] text-secondary flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
            AGENTS NEVER PUSH TO MAIN
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {STATS.map((stat) => (
            <div
              key={stat.label}
              className="p-4 rounded-lg bg-surface-container-low border border-outline-variant/40 flex items-center justify-between shadow-sm"
            >
              <div className="flex flex-col">
                <span className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider">
                  {stat.label}
                </span>
                <span className="text-xl text-white font-semibold mt-0.5">{stat.value}</span>
              </div>
              <span className={`material-symbols-outlined text-[26px] ${stat.color}`}>
                {stat.icon}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
