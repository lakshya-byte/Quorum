import Link from "next/link";
import { Badge, Icon, LinkButton, type IconName } from "../../_ui";
import { AgentTeam, SystemMap } from "./Diagrams";
import LiveDemo from "./LiveDemo";

function SectionHead({ eyebrow, title, body, id }: { eyebrow: string; title: string; body?: string; id?: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="text-[13px] font-medium text-primary">{eyebrow}</p>
      <h2 id={id} className="text-balance mt-2 text-[28px] font-semibold leading-tight tracking-tight text-white sm:text-[36px]">
        {title}
      </h2>
      {body && <p className="mt-3 text-[15px] leading-7 text-on-surface-variant">{body}</p>}
    </div>
  );
}

export function Hero() {
  return (
    <section className="relative overflow-hidden pt-28 sm:pt-32">
      <div aria-hidden className="dot-grid pointer-events-none absolute inset-0 [mask-image:radial-gradient(ellipse_at_top,black,transparent_70%)] opacity-70" />
      <div aria-hidden className="pointer-events-none absolute left-1/2 top-0 h-[420px] w-[820px] -translate-x-1/2 rounded-full bg-primary/10 blur-[120px]" />
      <div className="relative mx-auto max-w-6xl px-4 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <Link
            href="/try"
            className="focus-ring inline-flex items-center gap-2 rounded-full border border-border-strong bg-surface-container-low/70 px-3 py-1 text-[12.5px] text-on-surface-variant transition-colors hover:text-white"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-primary" />
            Try a live run, no account needed
            <Icon name="arrow-right" size={13} />
          </Link>
          <h1 className="text-balance mt-6 text-[36px] font-semibold leading-[1.08] tracking-tight text-white sm:text-[56px]">
            Describe the change.
            <br />
            <span className="bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent">Get a pull request its own checks already passed.</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-[16px] leading-7 text-on-surface-variant sm:text-[18px] sm:leading-8">
            Describe a bug, a feature, a refactor or a UI change. PatchLoop spawns a swarm sized to the task, runs it all in sandboxes, and opens a pull request only when its own checks pass. You merge.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <LinkButton href="/signup" size="lg" iconRight="arrow-right">
              Get started
            </LinkButton>
            <LinkButton href="/try" size="lg" variant="secondary" icon="play">
              Watch a live run
            </LinkButton>
          </div>
          <p className="mt-4 text-[13px] text-text-subtle">Works offline in demo mode with bundled repositories. No keys needed to try it.</p>
        </div>
        <div className="mx-auto mt-14 max-w-5xl sm:mt-16">
          <LiveDemo />
          <p className="mt-3 text-center text-[12.5px] text-text-subtle">A scripted replay of a UI task, drawn by the same pipeline and agent components the live run page uses. Not a live run.</p>
        </div>
      </div>
    </section>
  );
}

const FACTS: { value: string; label: string; body: string }[] = [
  { value: "10", label: "task types", body: "Bug fix, feature, refactor, UI, tests, performance, dependencies, docs, migration, other. Auto picks one, or you choose." },
  { value: "2", label: "kinds of check", body: "Hard gates decide and are run by plain code. Advisory checks are model opinions: shown, never blocking." },
  { value: "0", label: "merge calls in the agent", body: "The agent service has no merge function. A test greps for it." },
  { value: "4", label: "ways to start a task", body: "Website, CLI, Slack and GitHub issues. Slack and GitHub need app setup." },
];

export function ProofStrip() {
  return (
    <section aria-label="How it is built" className="mx-auto mt-24 max-w-6xl px-4 lg:px-8">
      <dl className="grid gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
        {FACTS.map((f) => (
          <div key={f.label} className="bg-panel p-6">
            <dt className="sr-only">{f.label}</dt>
            <dd>
              <div className="text-[40px] font-semibold leading-none tracking-tight text-white">{f.value}</div>
              <div className="mt-2 text-[14px] font-medium text-white">{f.label}</div>
              <p className="mt-1.5 text-[13px] leading-5 text-on-surface-variant">{f.body}</p>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

const STEPS: { icon: IconName; title: string; body: string }[] = [
  { icon: "github", title: "Connect GitHub", body: "Install the GitHub App and grant only the repositories you choose." },
  { icon: "folder", title: "Pick a repo and describe the task", body: "A bug, a feature, a refactor or a UI change, in plain English. Vague? It asks questions instead of guessing." },
  { icon: "crosshair", title: "Plan and write the checks", body: "A planner picks the task type and the checks that will prove it. Spec agents write the tests or UI scripts and validate them on the original code." },
  { icon: "sparkles", title: "A swarm sized to the task", body: "Independent units run in parallel, each variant in its own sandbox fork. The first variant to pass its unit wins; the rest are cancelled." },
  { icon: "split", title: "Merge and verify", body: "An integrator combines the units. Plain code then runs every hard gate; if one fails, a critic writes repair units for another round." },
  { icon: "git-pr", title: "Open a pull request", body: "One commit per unit on a patchloop/ branch, with the evidence: gates, advisory scores, before and after screenshots for UI work." },
  { icon: "check-circle", title: "You review and merge", body: "Checks shown on the PR. Ask for changes, or press Merge yourself. A partial result says what could not be proven." },
];

export function Flow() {
  return (
    <section id="how" aria-labelledby="how-h" className="mx-auto mt-28 max-w-6xl scroll-mt-20 px-4 lg:px-8">
      <SectionHead eyebrow="How it works" id="how-h" title="From a sentence to a reviewed pull request in seven steps" body="Every agent, tool call and check is visible while it happens, so you are never asked to trust a black box." />
      <ol className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((s, i) => (
          <li key={s.title} className={`group relative rounded-xl border border-border bg-panel p-5 transition-colors hover:border-border-strong ${i === 6 ? "sm:col-span-2 lg:col-span-1" : ""}`}>
            <div className="flex items-center justify-between">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-border-strong bg-surface-container-low text-primary">
                <Icon name={s.icon} size={17} />
              </span>
              <span className="font-mono text-[12px] text-text-subtle">0{i + 1}</span>
            </div>
            <h3 className="mt-4 text-[15px] font-semibold text-white">{s.title}</h3>
            <p className="mt-1.5 text-[13.5px] leading-6 text-on-surface-variant">{s.body}</p>
          </li>
        ))}
        <li className="flex flex-col justify-center rounded-xl border border-dashed border-primary/40 bg-primary/5 p-5 sm:col-span-2 lg:col-span-1">
          <p className="text-[15px] font-semibold text-primary">Agents propose. Checks decide. You merge.</p>
          <p className="mt-1.5 text-[13.5px] leading-6 text-on-surface-variant">If the hard gates cannot be met you get an honest &quot;failed&quot; with every check result. No pull request is opened.</p>
        </li>
      </ol>
    </section>
  );
}

const VERIFY: { type: string; hard: string; advisory: string }[] = [
  { type: "Every task", hard: "Build or compile succeeds. Every test that passed on the original still passes. Path policy (no .github/, no edits to existing tests). No new high-severity scan findings. No secret-looking strings.", advisory: "Plan adherence: did the changes stay inside each unit's scope (model review)." },
  { type: "Bug fix", hard: "A reproducer test fails on the original code and passes now.", advisory: "Readability of the diff." },
  { type: "Feature", hard: "Acceptance tests are written first from your description. They must fail on the original and pass now.", advisory: "Readability and fit with surrounding code." },
  { type: "Refactor", hard: "Characterization tests generated from the original pass before and after. Public API surface unchanged. Lint no worse. A size or duplication target, if you state one, is measured.", advisory: "Whether the new module boundaries are sensible." },
  { type: "UI/UX", hard: "No console errors, no horizontal overflow at 375, 768 and 1280 px, no new axe-core violations, and a key-flow script passes before and after.", advisory: "Whether it looks better: a vision model scores before and after screenshots. This is an opinion, so it never blocks unless you promote it." },
  { type: "Tests, performance, dependencies, docs, other", hard: "The planner must write at least one executable check: a command's exit code, a benchmark threshold, an audit or lockfile result, a link checker.", advisory: "Anything with no executable check, such as whether prose reads well. If nothing executable exists the result is Partial and the pull request says exactly what was not verified." },
];

export function Verification() {
  return (
    <section id="verification" aria-labelledby="verify-h" className="mx-auto mt-28 max-w-6xl scroll-mt-20 px-4 lg:px-8">
      <SectionHead
        eyebrow="How verification works"
        id="verify-h"
        title="Hard gates decide. Advisory checks inform."
        body="Models write the code and write the checks. Plain code runs them. A result is Complete only when every hard gate passes; you can promote any advisory check to a hard gate when you start a task."
      />
      <div className="mt-12 hidden overflow-hidden rounded-2xl border border-border bg-panel md:block">
        <table className="w-full text-left text-[13.5px]">
          <caption className="sr-only">Hard gates and advisory checks for each task type</caption>
          <thead>
            <tr className="border-b border-border text-[12px] text-on-surface-variant">
              <th scope="col" className="w-[190px] px-5 py-3 font-medium">Task type</th>
              <th scope="col" className="px-5 py-3 font-medium">Hard gates (must pass)</th>
              <th scope="col" className="px-5 py-3 font-medium">Advisory (reported, never blocking)</th>
            </tr>
          </thead>
          <tbody>
            {VERIFY.map((v) => (
              <tr key={v.type} className="border-b border-border/60 align-top last:border-0">
                <th scope="row" className="px-5 py-4 text-left font-semibold text-white">{v.type}</th>
                <td className="px-5 py-4 leading-6 text-on-surface">{v.hard}</td>
                <td className="px-5 py-4 leading-6 text-on-surface-variant">{v.advisory}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="mt-10 grid gap-3 md:hidden">
        {VERIFY.map((v) => (
          <li key={v.type} className="rounded-xl border border-border bg-panel p-4">
            <h3 className="text-[15px] font-semibold text-white">{v.type}</h3>
            <p className="mt-2 text-[13.5px] leading-6 text-on-surface"><Badge tone="success" className="mr-1.5">hard</Badge>{v.hard}</p>
            <p className="mt-2 text-[13.5px] leading-6 text-on-surface-variant"><Badge tone="warning" className="mr-1.5">advisory</Badge>{v.advisory}</p>
          </li>
        ))}
      </ul>
      <div className="mx-auto mt-8 max-w-3xl rounded-xl border border-dashed border-warning/40 bg-warning/5 p-4 text-[13.5px] leading-6 text-on-surface-variant">
        <b className="text-warning">What this does not prove.</b> Passing every hard gate means the checks PatchLoop could write and run were met. It does not prove the change is what you meant, that a visual result is good, or that code outside the checks is untouched. That is why the result is a pull request, and a person merges it.
      </div>
    </section>
  );
}

export function Diagrams() {
  return (
    <section aria-labelledby="diagrams-h" className="mx-auto mt-28 max-w-6xl px-4 lg:px-8">
      <SectionHead eyebrow="Under the hood" id="diagrams-h" title="A swarm sized to the task, with guard rails at every hand-off" body="Two views: how PatchLoop connects to your tools, and how the swarm hands work along. Designed for large repos: a repo map, sparse context for each worker, and token, time and worker budgets." />
      <div className="mt-12 grid gap-6">
        <figure className="rounded-2xl border border-border bg-panel p-5 sm:p-8">
          <figcaption className="mb-5 flex items-center gap-2 text-[14px] font-semibold text-white">
            <Icon name="layers" size={16} className="text-primary" /> System map
            <Badge tone="warning" className="ml-1">agents never merge</Badge>
          </figcaption>
          <SystemMap />
        </figure>
        <figure className="rounded-2xl border border-border bg-panel p-5 sm:p-8">
          <figcaption className="mb-5 flex items-center gap-2 text-[14px] font-semibold text-white">
            <Icon name="split" size={16} className="text-primary" /> The swarm: planner, spec agents, parallel workers, integrator, verifiers, PR
          </figcaption>
          <AgentTeam />
        </figure>
      </div>
    </section>
  );
}

function Terminal() {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-[#05070a] font-mono text-[12px] leading-[1.7] text-on-surface-variant">
      <div className="flex gap-1.5 border-b border-border px-3 py-2" aria-hidden>
        <span className="h-2 w-2 rounded-full bg-border-strong" />
        <span className="h-2 w-2 rounded-full bg-border-strong" />
        <span className="h-2 w-2 rounded-full bg-border-strong" />
      </div>
      <pre className="overflow-x-auto p-3.5 [font-variant-ligatures:none]">
        <span className="text-primary">$</span> <span className="text-white">patchloop do --repo demo/shop-api \</span>
        {"\n"}    <span className="text-white">&quot;Add bulk discount tiers&quot;</span>
        {"\n"}
        {"\n"}
        <span className="text-secondary">plan</span>    feature · 6 hard gates, 2 advisory{"\n"}
        <span className="text-secondary">agents</span>  spec-1 w-u1-a w-u1-b w-u2-a{"\n"}
        <span className="text-secondary">verify</span>  6/6 hard gates pass{"\n"}
        <span className="text-secondary">outcome</span> <span className="text-primary">complete</span>, exit code 0{"\n"}
        <span className="text-secondary">pr</span>      <span className="text-white">patchloop/add-bulk-discount-tiers</span>
      </pre>
    </div>
  );
}

function SlackMock() {
  return (
    <div className="rounded-lg border border-border bg-[#05070a] p-3.5 text-[12.5px] leading-5">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded bg-primary/20 text-[11px] font-bold text-primary">P</span>
        <span className="font-semibold text-white">PatchLoop</span>
        <span className="rounded bg-surface-container-high px-1 text-[10px] text-on-surface-variant">APP</span>
      </div>
      <p className="mt-2 text-on-surface">
        <b className="text-white">Complete:</b> bulk discount tiers added. 6/6 hard gates passed, 3 commits, one per unit. Advisory: readability 0.86.
      </p>
      <p className="font-mono text-[11.5px] text-on-surface-variant">demo/shop-api · PR #42</p>
      <div className="mt-2.5 flex flex-wrap gap-2" aria-hidden>
        <span className="rounded border border-border-strong px-2.5 py-1 text-[12px] font-medium text-white">Review</span>
        <span className="rounded border border-primary/60 bg-primary/10 px-2.5 py-1 text-[12px] font-medium text-primary">Merge</span>
        <span className="rounded border border-border-strong px-2.5 py-1 text-[12px] font-medium text-white">Ask for changes</span>
      </div>
    </div>
  );
}

function GithubMock() {
  return (
    <div className="rounded-lg border border-border bg-[#05070a] p-3.5 text-[12.5px] leading-5">
      <div className="flex items-center gap-2">
        <Icon name="github" size={15} className="text-on-surface-variant" />
        <span className="font-medium text-white">Add bulk discount tiers</span>
        <span className="text-text-subtle">#17</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5" aria-hidden>
        <span className="rounded-full border border-primary/50 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">patchloop</span>
        <span className="rounded-full border border-border-strong px-2 py-0.5 text-[11px] text-on-surface-variant">bug</span>
      </div>
      <div className="mt-2.5 rounded border border-border p-2.5 text-on-surface-variant">
        <b className="text-white">patchloop[bot]</b> PatchLoop is on it: <span className="text-secondary">run link</span>
      </div>
    </div>
  );
}

function WebMock() {
  return (
    <div className="rounded-lg border border-border bg-[#05070a] p-3.5 text-[12.5px]">
      <div className="flex items-center gap-2 font-mono text-on-surface-variant">
        <Icon name="github" size={14} /> demo/react-todo <Icon name="git-branch" size={13} /> main
      </div>
      <div className="mt-2.5 rounded-md border border-border-strong bg-surface-container-low px-2.5 py-2 text-on-surface">Improve the UI of this React app</div>
      <div className="mt-2.5 flex flex-wrap gap-1.5" aria-hidden>
        {["Plan", "UI checks", "Restyle", "Merge", "Verify", "Review"].map((s, i) => (
          <span key={s} className={`rounded px-1.5 py-0.5 text-[11px] ${i < 5 ? "bg-primary/15 text-primary" : "bg-secondary/15 text-secondary"}`}>
            {s}
          </span>
        ))}
      </div>
      <div className="mt-2.5 flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-2" aria-hidden>
        <Icon name="git-pr" size={14} className="text-primary" />
        <span className="flex-1 text-white">PR #7 ready for review</span>
        <span className="rounded border border-border-strong px-2 py-0.5 text-[11px] text-on-surface-variant">Checks passing</span>
      </div>
    </div>
  );
}

export function EntryPoints() {
  const items: { icon: IconName; title: string; body: string; mock: React.ReactNode; note?: string }[] = [
    { icon: "panel", title: "Website", body: "Pick a repo, choose a task type or leave it on Auto, and watch every agent live. Review the diff and artifacts, check CI, merge.", mock: <WebMock /> },
    { icon: "terminal", title: "CLI", body: "patchloop do streams the same live view in your terminal. The exit code says complete, partial, failed, error or needs input (patchloop fix still works).", mock: <Terminal /> },
    { icon: "slack", title: "Slack", body: "Run /patchloop fix or mention the bot with a task. Progress arrives in a thread, with Merge and Ask for changes buttons; a partial result shows a warning.", mock: <SlackMock />, note: "Needs the Slack app set up by whoever runs the server" },
    { icon: "github", title: "GitHub issues", body: "Add the patchloop label (and optionally patchloop:feature, :refactor, :ui or :bugfix), or comment @patchloop fix, and a run starts. The pull request links back to it.", mock: <GithubMock />, note: "Needs the GitHub App with webhooks enabled" },
  ];
  return (
    <section id="entry-points" aria-labelledby="entry-h" className="mx-auto mt-28 max-w-6xl scroll-mt-20 px-4 lg:px-8">
      <SectionHead eyebrow="Where you start" id="entry-h" title="Start from wherever the work shows up" body="Four entry points, one engine. Every route ends at the same place: a pull request that a human merges." />
      <div className="mt-12 grid gap-4 md:grid-cols-2">
        {items.map((it) => (
          <article key={it.title} className="flex min-w-0 flex-col gap-4 rounded-2xl border border-border bg-panel p-5 transition-colors hover:border-border-strong sm:p-6">
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border-strong bg-surface-container-low text-primary">
                <Icon name={it.icon} size={17} />
              </span>
              <div>
                <h3 className="text-[16px] font-semibold text-white">{it.title}</h3>
                <p className="mt-1 text-[14px] leading-6 text-on-surface-variant">{it.body}</p>
                {it.note && <Badge tone="warning" className="mt-2 !h-auto !whitespace-normal py-1 leading-4">{it.note}</Badge>}
              </div>
            </div>
            <div className="mt-auto">{it.mock}</div>
          </article>
        ))}
      </div>
    </section>
  );
}

const TRUST: { icon: IconName; title: string; body: string }[] = [
  { icon: "flask", title: "Checks are the judge", body: "A result is Complete only if every hard gate passes, and plain code runs the gates. A model's opinion can inform you but never approve its own work." },
  { icon: "box", title: "Sandboxed candidates", body: "In live mode each worker and verifier runs in an isolated Nebius sandbox fork, not on your machine or your CI. Demo mode runs bundled repos in a local temp directory. Whether the Node and headless-browser sandbox images can be pulled is not verified here." },
  { icon: "git-pr", title: "Pull requests only", body: "Branches are always patchloop/…. The code refuses anything else, and never writes to your default branch." },
  { icon: "user", title: "A human merges", body: "The agent service has no merge function. Merge is a button you press, under your own GitHub permission." },
  { icon: "shield-check", title: "Policy and security gates", body: "Workers can't touch CI files, existing tests or paths outside their unit, and a security scan flags new findings before anything is proposed." },
  { icon: "eye", title: "Honest modes", body: "Demo mode is labelled everywhere: fake model, bundled repos, simulated pull requests. Failed and partial runs say so, and say what was not verified." },
];

export function Trust() {
  return (
    <section id="trust" aria-labelledby="trust-h" className="mx-auto mt-28 max-w-6xl scroll-mt-20 px-4 lg:px-8">
      <SectionHead eyebrow="Trust" id="trust-h" title="Built so you never have to take its word for it" />
      <ul className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
        {TRUST.map((t) => (
          <li key={t.title} className="bg-panel p-6">
            <Icon name={t.icon} size={20} className="text-primary" />
            <h3 className="mt-4 text-[15px] font-semibold text-white">{t.title}</h3>
            <p className="mt-1.5 text-[13.5px] leading-6 text-on-surface-variant">{t.body}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

const FAQ: [string, string][] = [
  ["Does PatchLoop ever merge code by itself?", "No. It opens a pull request on a patchloop/ branch. Merging is a separate action that you take, using your own GitHub permission, and it is refused unless checks have passed (or no CI is configured, in which case you are warned). A partial result shows an extra warning."],
  ["What kinds of tasks work?", "Bug fixes, features, refactors, UI changes, tests, performance, dependency upgrades and docs. Each gets checks written for it. The checks are only as good as what can be run: a UI task has real before and after screenshots and mechanical gates, but whether it looks better is a model's opinion and stays advisory."],
  ["What if the task is vague or cannot be verified?", "Vague: the planner asks you questions instead of guessing. Not fully verifiable: the planner must still write at least one executable check; if none can exist, the result is Partial and the pull request lists what was not verified. It is never declined for being untestable."],
  ["What happens when the checks cannot be met?", "The run ends as failed, with every check result and the best attempt visible. Nothing is opened for merge."],
  ["Which languages work?", "Python projects (unittest or pytest) are the most exercised path. Node and Go are best effort. UI checks need a headless browser in the sandbox; where that is missing the visual checks report skip with the reason."],
  ["Does it work on large repositories?", "It is designed for them: a deterministic repo map, workers that see only their unit's files, test selection, and token, time and worker budgets. That is a design statement, not a benchmark; there are no performance numbers here."],
  ["Can I try it without any keys?", "Yes. Demo mode uses a scripted model, a local sandbox and bundled repositories, with simulated pull requests. It is labelled as demo everywhere."],
  ["Where does my code go?", "In live mode, the task and the relevant files are sent to models hosted on Nebius, and work runs in Nebius sandboxes. Tokens for GitHub are encrypted at rest and never logged."],
  ["Do Slack and GitHub triggers work out of the box?", "Only once the operator of the server has created the Slack app and the GitHub App and set their credentials. The website and CLI need neither."],
  ["What does it cost?", "PatchLoop is a hackathon project. There is no pricing page and no paid plan."],
];

export function Faq() {
  return (
    <section id="faq" aria-labelledby="faq-h" className="mx-auto mt-28 max-w-3xl scroll-mt-20 px-4 lg:px-8">
      <SectionHead eyebrow="FAQ" id="faq-h" title="Straight answers" />
      <div className="mt-10 divide-y divide-border rounded-2xl border border-border bg-panel">
        {FAQ.map(([q, a]) => (
          <details key={q} className="group px-5 py-4">
            <summary className="focus-ring flex cursor-pointer list-none items-center justify-between gap-4 rounded text-[15px] font-medium text-white">
              {q}
              <Icon name="chevron-down" size={16} className="shrink-0 text-on-surface-variant transition-transform group-open:rotate-180" />
            </summary>
            <p className="mt-3 text-[14px] leading-7 text-on-surface-variant">{a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

export function FinalCta() {
  return (
    <section aria-label="Get started" className="mx-auto my-28 max-w-6xl px-4 lg:px-8">
      <div className="relative overflow-hidden rounded-3xl border border-border-strong bg-panel px-6 py-14 text-center sm:px-12">
        <div aria-hidden className="pointer-events-none absolute left-1/2 top-0 h-48 w-[640px] -translate-x-1/2 rounded-full bg-primary/15 blur-[90px]" />
        <h2 className="text-balance relative text-[30px] font-semibold leading-tight tracking-tight text-white sm:text-[40px]">Point it at a real task.</h2>
        <p className="relative mx-auto mt-3 max-w-xl text-[15px] leading-7 text-on-surface-variant">Create an account, connect a repository (or the demo account), describe the change, and review your first pull request.</p>
        <div className="relative mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <LinkButton href="/signup" size="lg" iconRight="arrow-right">
            Create an account
          </LinkButton>
          <LinkButton href="/try" size="lg" variant="secondary" icon="play">
            Try the live demo
          </LinkButton>
        </div>
      </div>
    </section>
  );
}
