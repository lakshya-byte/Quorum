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
            Describe a bug.
            <br />
            <span className="bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent">Get a pull request your tests already passed.</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-[16px] leading-7 text-on-surface-variant sm:text-[18px] sm:leading-8">
            PatchLoop reads your repository, writes a failing test, and has a team of AI agents try fixes in parallel sandboxes. Only a change that passes your tests becomes a pull request, and only you can merge it.
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
          <p className="mt-3 text-center text-[12.5px] text-text-subtle">A scripted replay of a demo run, drawn by the same attempt-tree component the live run page uses.</p>
        </div>
      </div>
    </section>
  );
}

const FACTS: { value: string; label: string; body: string }[] = [
  { value: "8", label: "pipeline stages", body: "Repo, locate, repro, propose, test, critic, review, PR. Each one is visible live." },
  { value: "3", label: "parallel proposers", body: "Different strategies per round. The first candidate to pass everything wins." },
  { value: "0", label: "merge calls in the agent", body: "The agent service has no merge function. A test greps for it." },
  { value: "4", label: "ways to start a fix", body: "Website, CLI, Slack and GitHub issues. Slack and GitHub need app setup." },
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
  { icon: "folder", title: "Pick a repo and describe the bug", body: "Plain English, or paste the error or stack trace." },
  { icon: "crosshair", title: "Locate and reproduce", body: "Agents find the files that matter and write a test that fails today." },
  { icon: "sparkles", title: "Propose in parallel", body: "Several candidate fixes per round, each a real multi-file patch." },
  { icon: "flask", title: "Test in sandboxes", body: "Every candidate runs your suite in isolation. A critic learns from failures." },
  { icon: "git-pr", title: "Open a pull request", body: "On a patchloop/ branch, with the cause, the change and the proof." },
  { icon: "check-circle", title: "You review and merge", body: "Checks shown on the PR. Ask for changes, or press Merge yourself." },
];

export function Flow() {
  return (
    <section id="how" aria-labelledby="how-h" className="mx-auto mt-28 max-w-6xl scroll-mt-20 px-4 lg:px-8">
      <SectionHead eyebrow="How it works" id="how-h" title="From a sentence to a reviewed pull request in seven steps" body="Every step is visible while it happens, so you are never asked to trust a black box." />
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
          <p className="text-[15px] font-semibold text-primary">Agents propose. Tests decide. You merge.</p>
          <p className="mt-1.5 text-[13.5px] leading-6 text-on-surface-variant">If nothing passes, you get the best attempt and an honest &quot;unsolved&quot;. No pull request is opened.</p>
        </li>
      </ol>
    </section>
  );
}

export function Diagrams() {
  return (
    <section aria-labelledby="diagrams-h" className="mx-auto mt-28 max-w-6xl px-4 lg:px-8">
      <SectionHead eyebrow="Under the hood" id="diagrams-h" title="A team of agents, with guard rails at every hand-off" body="Two views: how PatchLoop connects to your tools, and how the agents hand work to each other." />
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
            <Icon name="split" size={16} className="text-primary" /> The agent team
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
        <span className="text-primary">$</span> <span className="text-white">patchloop fix --repo demo/inventory-api \</span>
        {"\n"}    <span className="text-white">&quot;reserving the last unit fails&quot;</span>
        {"\n"}
        {"\n"}
        <span className="text-secondary">repo</span>    3 files · Python{"\n"}
        <span className="text-secondary">locate</span>  inventory/stock.py, api.py{"\n"}
        <span className="text-secondary">repro</span>   test_reserve_last_unit fails ✓{"\n"}
        <span className="text-secondary">round 1</span> #1 2/3  #2 2/3  #3 blocked{"\n"}
        <span className="text-secondary">round 2</span> #4 <span className="text-primary">3/3 winner</span>{"\n"}
        <span className="text-secondary">pr</span>      <span className="text-white">patchloop/reserve-last-unit</span>
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
        <b className="text-white">Fixed:</b> reserving the last unit now works. Reproducer and suite pass (3/3), security scan clean.
      </p>
      <p className="font-mono text-[11.5px] text-on-surface-variant">demo/inventory-api · PR #42</p>
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
        <span className="font-medium text-white">Last unit can&apos;t be reserved</span>
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
        <Icon name="github" size={14} /> demo/inventory-api <Icon name="git-branch" size={13} /> main
      </div>
      <div className="mt-2.5 rounded-md border border-border-strong bg-surface-container-low px-2.5 py-2 text-on-surface">Reserving the last unit of an item fails with &quot;out of stock&quot;.</div>
      <div className="mt-2.5 flex flex-wrap gap-1.5" aria-hidden>
        {["Repo", "Locate", "Repro", "Propose", "Test", "Critic"].map((s, i) => (
          <span key={s} className={`rounded px-1.5 py-0.5 text-[11px] ${i < 5 ? "bg-primary/15 text-primary" : "bg-secondary/15 text-secondary"}`}>
            {s}
          </span>
        ))}
      </div>
      <div className="mt-2.5 flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-2" aria-hidden>
        <Icon name="git-pr" size={14} className="text-primary" />
        <span className="flex-1 text-white">PR #42 ready for review</span>
        <span className="rounded border border-border-strong px-2 py-0.5 text-[11px] text-on-surface-variant">Checks passing</span>
      </div>
    </div>
  );
}

export function EntryPoints() {
  const items: { icon: IconName; title: string; body: string; mock: React.ReactNode; note?: string }[] = [
    { icon: "panel", title: "Website", body: "Pick a repo, describe the bug and watch every attempt live. Review the diff, check CI, merge.", mock: <WebMock /> },
    { icon: "terminal", title: "CLI", body: "patchloop fix streams the same live view in your terminal. Exit code tells you if it was solved.", mock: <Terminal /> },
    { icon: "slack", title: "Slack", body: "Run /patchloop fix or mention the bot with an alert. Progress arrives in a thread, with Merge and Ask for changes buttons.", mock: <SlackMock />, note: "Needs the Slack app set up by whoever runs the server" },
    { icon: "github", title: "GitHub issues", body: "Add the patchloop label, or comment @patchloop fix, and a run starts. The pull request links back to it.", mock: <GithubMock />, note: "Needs the GitHub App with webhooks enabled" },
  ];
  return (
    <section id="entry-points" aria-labelledby="entry-h" className="mx-auto mt-28 max-w-6xl scroll-mt-20 px-4 lg:px-8">
      <SectionHead eyebrow="Where you start" id="entry-h" title="Start from wherever the bug shows up" body="Four entry points, one engine. Every route ends at the same place: a pull request that a human merges." />
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
  { icon: "flask", title: "Tests are the judge", body: "A fix counts only if the new reproducer and your existing suite pass. The AI does not grade itself." },
  { icon: "box", title: "Sandboxed candidates", body: "Each candidate runs in an isolated sandbox, never on your machine or your CI." },
  { icon: "git-pr", title: "Pull requests only", body: "Branches are always patchloop/…. The code refuses anything else, and never writes to your default branch." },
  { icon: "user", title: "A human merges", body: "The agent service has no merge function. Merge is a button you press, under your own GitHub permission." },
  { icon: "shield-check", title: "Policy and security gates", body: "Patches can't touch CI files or tests, and a security scan flags new findings before anything is proposed." },
  { icon: "eye", title: "Honest modes", body: "Demo mode is labelled everywhere: fake model, bundled repos, simulated pull requests. Unsolved runs say so." },
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
  ["Does PatchLoop ever merge code by itself?", "No. It opens a pull request on a patchloop/ branch. Merging is a separate action that you take, using your own GitHub permission, and it is refused unless checks have passed (or no CI is configured, in which case you are warned)."],
  ["What happens when no fix passes?", "The run ends as unsolved. You see the best attempt and its failing tests, and nothing is opened for merge."],
  ["Which languages work?", "Python projects (unittest or pytest) are the solid path. Node (npm test) and Go (go test) are best effort and marked as such."],
  ["Can I try it without any keys?", "Yes. Demo mode uses a fake model, a local sandbox and three bundled repositories, with simulated pull requests. It is labelled as demo everywhere."],
  ["Where does my code go?", "In live mode, the task and the relevant files are sent to models hosted on Nebius, and candidates run in Nebius sandboxes. Tokens for GitHub are encrypted at rest and never logged."],
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
        <h2 className="text-balance relative text-[30px] font-semibold leading-tight tracking-tight text-white sm:text-[40px]">Point it at a real bug.</h2>
        <p className="relative mx-auto mt-3 max-w-xl text-[15px] leading-7 text-on-surface-variant">Create an account, connect a repository (or the demo account), and review your first pull request.</p>
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
