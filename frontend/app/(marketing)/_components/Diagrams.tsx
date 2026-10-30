// Inline SVG diagrams. Colours come from CSS variables so they follow the theme.
// Wide variants show from md up; below that a vertical layout is used so labels stay readable.

const BOX = "fill-[var(--surface-container-low)] stroke-[var(--border-strong)]";
const BOX_ACCENT = "fill-[color-mix(in_srgb,var(--primary)_10%,var(--bg))] stroke-[var(--primary)]";
const BOX_INFO = "fill-[color-mix(in_srgb,var(--secondary)_8%,var(--bg))] stroke-[var(--secondary)]";
const T = "fill-[var(--on-surface)] text-[13px] font-medium";
const T2 = "fill-[var(--on-surface-variant)] text-[11.5px]";
const HEAD = "fill-[var(--text-subtle)] text-[11px] font-medium tracking-wider";

type Kind = "box" | "accent" | "info";

function Node({ x, y, w, h, title, sub, kind = "box" }: { x: number; y: number; w: number; h: number; title: string; sub?: string; kind?: Kind }) {
  const cls = kind === "accent" ? BOX_ACCENT : kind === "info" ? BOX_INFO : BOX;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={10} className={cls} strokeWidth={1.2} />
      <text x={x + w / 2} y={y + (sub ? h / 2 - 3 : h / 2 + 4.5)} textAnchor="middle" className={T}>
        {title}
      </text>
      {sub && (
        <text x={x + w / 2} y={y + h / 2 + 14} textAnchor="middle" className={T2}>
          {sub}
        </text>
      )}
    </g>
  );
}

function Flow({ d, dashed = true, tone = "primary" }: { d: string; dashed?: boolean; tone?: "primary" | "muted" | "warn" }) {
  const stroke = tone === "primary" ? "var(--primary)" : tone === "warn" ? "var(--warning)" : "var(--border-strong)";
  return <path d={d} fill="none" stroke={stroke} strokeWidth={1.6} className={dashed ? "flow-line" : undefined} markerEnd={`url(#arrow-${tone})`} />;
}

function Defs({ id }: { id: string }) {
  return (
    <defs>
      {(["primary", "muted", "warn"] as const).map((t) => (
        <marker key={t} id={`${id}-${t}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 9 5 1 9" fill="none" stroke={t === "primary" ? "var(--primary)" : t === "warn" ? "var(--warning)" : "var(--border-strong)"} strokeWidth="1.6" strokeLinecap="round" />
        </marker>
      ))}
    </defs>
  );
}

// marker ids are shared across the page (one set is enough); each svg defines the same ids.
function SharedDefs() {
  return <Defs id="arrow" />;
}

/** Diagram 1: system map. */
export function SystemMap() {
  return (
    <>
      <svg viewBox="0 0 900 330" role="img" aria-label="System map: you start a fix from the website, CLI, Slack or GitHub. PatchLoop reads your repo, spawns a swarm that calls Nebius models and sandboxes, opens a pull request on GitHub and messages Slack. You review and merge." className="hidden h-auto w-full md:block">
        <title>PatchLoop system map</title>
        <desc>Four entry points feed PatchLoop. PatchLoop talks to GitHub, Nebius and Slack. Agents never merge; a human does.</desc>
        <SharedDefs />
        <text x={20} y={26} className={HEAD}>
          YOU START A FIX FROM
        </text>
        {["Website", "CLI", "Slack", "GitHub issue"].map((l, i) => (
          <Node key={l} x={20} y={40 + i * 66} w={150} h={48} title={l} />
        ))}
        {[0, 1, 2, 3].map((i) => (
          <Flow key={i} d={`M170 ${64 + i * 66} C 230 ${64 + i * 66}, 240 ${175}, 296 175`} />
        ))}
        <rect x={300} y={95} width={250} height={160} rx={14} className={BOX_ACCENT} strokeWidth={1.4} />
        <text x={425} y={127} textAnchor="middle" className="fill-[var(--primary)] text-[15px] font-semibold">
          PatchLoop
        </text>
        <text x={425} y={155} textAnchor="middle" className={T2}>
          API and live run view
        </text>
        <text x={425} y={177} textAnchor="middle" className={T2}>
          swarm: planner, spec agents, workers,
        </text>
        <text x={425} y={195} textAnchor="middle" className={T2}>
          integrator, verifiers, reviewer
        </text>
        <text x={425} y={231} textAnchor="middle" className="fill-[var(--on-surface)] text-[12px] font-semibold">
          has no merge function
        </text>

        <Node x={700} y={40} w={180} h={64} title="GitHub" sub="reads repo, opens PR" />
        <Node x={700} y={143} w={180} h={64} title="Nebius" sub="models and sandboxes" kind="info" />
        <Node x={700} y={246} w={180} h={64} title="Slack" sub="progress and results" />
        <Flow d="M550 135 C 620 135, 630 88, 696 88" />
        <Flow d="M550 175 L 696 175" />
        <Flow d="M550 215 C 620 215, 630 278, 696 278" />

        <rect x={420} y={18} width={150} height={44} rx={9} fill="none" stroke="var(--warning)" strokeDasharray="4 4" strokeWidth={1.2} />
        <text x={495} y={37} textAnchor="middle" className="fill-[var(--warning)] text-[12px] font-semibold">
          you review
        </text>
        <text x={495} y={52} textAnchor="middle" className="fill-[var(--warning)] text-[12px] font-semibold">
          and press Merge
        </text>
        <Flow d="M570 40 C 630 40, 650 54, 696 54" tone="warn" />
      </svg>

      <svg viewBox="0 0 340 450" role="img" aria-label="System map: you start a fix from the website, CLI, Slack or GitHub. PatchLoop reads your repo, calls Nebius, opens a pull request on GitHub and messages Slack. You review and merge." className="mx-auto h-auto w-full max-w-sm md:hidden">
        <title>PatchLoop system map</title>
        <SharedDefs />
        <Node x={20} y={10} w={300} h={44} title="You: website, CLI, Slack or GitHub" />
        <Flow d="M170 54 L 170 94" />
        <rect x={20} y={96} width={300} height={110} rx={14} className={BOX_ACCENT} strokeWidth={1.4} />
        <text x={170} y={128} textAnchor="middle" className="fill-[var(--primary)] text-[15px] font-semibold">
          PatchLoop
        </text>
        <text x={170} y={152} textAnchor="middle" className={T2}>
          swarm: planner, spec agents, workers,
        </text>
        <text x={170} y={170} textAnchor="middle" className={T2}>
          integrator, verifiers, reviewer
        </text>
        <text x={170} y={194} textAnchor="middle" className="fill-[var(--on-surface)] text-[12px] font-semibold">
          has no merge function
        </text>
        <Flow d="M70 206 L 70 252" />
        <Flow d="M170 206 L 170 252" />
        <Flow d="M270 206 L 270 252" />
        <Node x={20} y={254} w={100} h={56} title="GitHub" sub="repo, PR" />
        <Node x={120} y={254} w={100} h={56} title="Nebius" sub="models" kind="info" />
        <Node x={220} y={254} w={100} h={56} title="Slack" sub="updates" />
        <Flow d="M70 310 L 70 350" tone="warn" />
        <rect x={20} y={352} width={300} height={56} rx={10} fill="none" stroke="var(--warning)" strokeDasharray="4 4" strokeWidth={1.2} />
        <text x={170} y={376} textAnchor="middle" className="fill-[var(--warning)] text-[13px] font-semibold">
          You review the pull request
        </text>
        <text x={170} y={394} textAnchor="middle" className="fill-[var(--warning)] text-[13px] font-semibold">
          and press Merge
        </text>
      </svg>
    </>
  );
}

const COLS: { x: number; head: string; boxes: { t: string; s: string; k?: Kind }[] }[] = [
  { x: 20, head: "PLAN", boxes: [{ t: "Input guard", s: "checks the task text" }, { t: "Repo map", s: "tree, symbols, tests" }, { t: "Planner", s: "type, criteria, units" }] },
  { x: 200, head: "SPEC AGENTS", boxes: [{ t: "Baseline", s: "build and tests, original" }, { t: "Write checks", s: "tests, UI scripts" }, { t: "Validate", s: "must run, fail first", k: "accent" }] },
  { x: 380, head: "WORKERS, IN PARALLEL", boxes: [{ t: "Worker A", s: "sandbox fork", k: "info" }, { t: "Worker B", s: "sandbox fork", k: "info" }, { t: "Worker C", s: "other unit", k: "info" }] },
  { x: 560, head: "COMBINE AND CHECK", boxes: [{ t: "Integrator", s: "merges unit diffs" }, { t: "Verifiers", s: "plain code, not an LLM", k: "accent" }, { t: "Critic", s: "repair units if a gate fails" }] },
  { x: 740, head: "SHIP", boxes: [{ t: "Reviewer", s: "drafts the PR text" }, { t: "Output guard", s: "checks the PR text" }, { t: "Pull request", s: "a human merges", k: "accent" }] },
];

/** Diagram 2: the swarm. */
export function AgentTeam() {
  const Y = [44, 124, 204];
  return (
    <>
      <svg viewBox="0 0 900 340" role="img" aria-label="Swarm: input guard, repo map and planner; spec agents write and validate the checks; workers run in parallel in sandbox forks; an integrator merges their diffs, deterministic verifiers run every check and a critic writes repair units if a hard gate fails; then a reviewer, output guard and a pull request that a human merges." className="hidden h-auto w-full md:block">
        <title>PatchLoop swarm</title>
        <desc>A guard, a repo map and a planner prepare the run. Spec agents write the checks and validate them on the original code. Workers run in parallel in sandbox forks. An integrator merges unit diffs, deterministic verifiers run every check, and a critic writes repair units when a hard gate fails. A reviewer and output guard precede the pull request, which a human merges.</desc>
        <SharedDefs />
        {COLS.map((c) => (
          <g key={c.head}>
            <text x={c.x} y={28} className={HEAD}>
              {c.head}
            </text>
            {c.boxes.map((b, i) => (
              <Node key={b.t} x={c.x} y={Y[i]} w={140} h={56} title={b.t} sub={b.s} kind={b.k} />
            ))}
            {[0, 1].map((i) => (
              <path key={i} d={`M${c.x + 70} ${Y[i] + 56} L ${c.x + 70} ${Y[i + 1]}`} stroke="var(--border-strong)" strokeWidth={1.4} fill="none" />
            ))}
          </g>
        ))}
        {[0, 1, 2, 3].map((i) => (
          <Flow key={i} d={`M${160 + i * 180} 152 L ${196 + i * 180} 152`} />
        ))}
        {/* loop back: critic -> proposers */}
        <path d="M630 260 L 630 296 L 270 296 L 270 264" fill="none" stroke="var(--warning)" strokeWidth={1.6} className="flow-line" markerEnd="url(#arrow-warn)" />
        <text x={450} y={316} textAnchor="middle" className="fill-[var(--warning)] text-[12px] font-medium">
          a hard gate failed: the critic writes repair units for the next round
        </text>
      </svg>

      <ol className="grid gap-2 md:hidden" aria-label="Swarm steps">
        {[
          ["Input guard", "checks the task text before anything runs"],
          ["Repo map and planner", "code builds a map; the planner picks the task type, the checks and the units"],
          ["Spec agents", "write tests or UI scripts and validate them on the original code"],
          ["Parallel workers", "each unit variant runs in its own sandbox fork; the first to pass wins"],
          ["Integrator", "merges the unit diffs and resolves conflicts"],
          ["Verifiers", "plain code runs every hard gate and advisory check"],
          ["Critic", "if a hard gate fails, writes repair units for the next round"],
          ["Reviewer and output guard", "draft and check the pull request text"],
          ["Pull request", "one commit per unit on a patchloop/ branch; a human merges"],
        ].map(([t, s], i) => (
          <li key={t} className="flex gap-3 rounded-lg border border-border bg-surface-container-low px-3.5 py-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border-strong text-[12px] font-semibold text-primary">{i + 1}</span>
            <span className="text-[13.5px] leading-5">
              <span className="font-semibold text-white">{t}</span>
              <span className="text-on-surface-variant">: {s}</span>
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
