"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { errorMessage, githubApi, runsApi, slackApi, type Bug, type GithubStatus, type Run, type SlackStatus } from "../../_lib/api";
import { RequireAuth, useAuth } from "../../_lib/auth";
import { isFinishedRun } from "../../_lib/useRunStream";
import { fmtMs } from "../../_components/run/NodeCard";
import { Badge, Card, EmptyState, ErrorNote, Icon, LinkButton, PageHeader, Skeleton, StatusChip, cx, type RunStatus } from "../../_ui";

function statusOf(r: Run): RunStatus {
  if (!isFinishedRun(r)) return "running";
  if (r.solved) return "solved";
  if ((r.status || "").toLowerCase() === "failed") return "failed";
  return "unsolved";
}

function bestTests(r: Run): string {
  const nodes = r.nodes || [];
  const best = r.bestNodeId != null ? nodes.find((n) => n.id === r.bestNodeId) : undefined;
  const pick = best ?? [...nodes].sort((a, b) => b.passed / (b.total || 1) - a.passed / (a.total || 1))[0];
  return pick ? `${pick.passed}/${pick.total}` : "–";
}

function tokens(r: Run): string {
  const t = r.cost?.tokens || (r.usage?.prompt_tokens || 0) + (r.usage?.completion_tokens || 0);
  return t ? t.toLocaleString() : "–";
}

function when(iso: string) {
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} min ago`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} h ago`;
  return d.toLocaleDateString();
}

function title(r: Run, bugs: Bug[] | null) {
  if (r.kind === "repo") return r.task || r.repo || "Repository fix";
  return bugs?.find((b) => b.id === r.bugId)?.title ?? r.bugId;
}

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[12.5px] text-on-surface-variant">{label}</div>
      <div className="mt-1 text-[28px] font-semibold leading-none tracking-tight text-white tabular-nums">{value}</div>
      {hint && <div className="mt-1.5 text-[12px] text-text-subtle">{hint}</div>}
    </Card>
  );
}

function Checklist({ gh, slack, runs }: { gh: GithubStatus | null; slack: SlackStatus | null; runs: Run[] | null }) {
  const items = [
    { done: !!gh?.connected, title: "Connect GitHub", body: "Install the GitHub App, or use the offline demo account.", href: "/integrations", cta: "Connect" },
    { done: !!runs && runs.some((r) => r.kind === "repo"), title: "Fix your first bug", body: "Pick a repository and describe the problem.", href: "/new", cta: "Start", locked: !gh?.connected },
    { done: !!slack?.configured, title: "Add Slack (optional)", body: "Get a message when a run finishes.", href: "/integrations", cta: "Set up" },
  ];
  const doneCount = items.filter((i) => i.done).length;
  if (gh && slack && runs && doneCount === items.length) return null;
  return (
    <Card className="p-5" data-testid="checklist">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold text-white">Get set up</h2>
          <p className="text-[13px] text-on-surface-variant">{doneCount} of {items.length} done</p>
        </div>
        <div className="h-1.5 w-32 overflow-hidden rounded-full bg-surface-container-high" aria-hidden>
          <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${(doneCount / items.length) * 100}%` }} />
        </div>
      </div>
      <ol className="mt-4 grid gap-3 md:grid-cols-3">
        {items.map((it, i) => (
          <li key={it.title} className={cx("flex flex-col gap-2 rounded-lg border p-4", it.done ? "border-primary/30 bg-primary/5" : "border-border bg-surface-container-low")}>
            <div className="flex items-center gap-2">
              <span className={cx("flex h-6 w-6 items-center justify-center rounded-full border text-[12px] font-semibold", it.done ? "border-primary bg-primary text-[#04120c]" : "border-border-strong text-on-surface-variant")}>
                {it.done ? <Icon name="check" size={13} strokeWidth={3} /> : i + 1}
              </span>
              <span className="text-[14px] font-medium text-white">{it.title}</span>
            </div>
            <p className="text-[13px] leading-5 text-on-surface-variant">{it.body}</p>
            {!it.done && (
              <div className="mt-auto pt-1">
                {it.locked ? (
                  <span className="text-[12.5px] text-text-subtle">Connect GitHub first</span>
                ) : (
                  <Link href={it.href} className="focus-ring inline-flex items-center gap-1 rounded text-[13px] font-medium text-primary hover:underline">
                    {it.cta} <Icon name="arrow-right" size={13} />
                  </Link>
                )}
              </div>
            )}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function DashboardInner() {
  const { user } = useAuth();
  const [bugs, setBugs] = useState<Bug[] | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [gh, setGh] = useState<GithubStatus | null>(null);
  const [slack, setSlack] = useState<SlackStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRuns((await runsApi.list()) || []);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    runsApi.bugs().then((b) => setBugs(b || [])).catch(() => setBugs([]));
    githubApi.status().then(setGh).catch(() => {});
    slackApi.get().then(setSlack).catch(() => {});
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    load();
  }, [load]);

  const anyRunning = (runs || []).some((r) => !isFinishedRun(r));
  useEffect(() => {
    if (!anyRunning) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [anyRunning, load]);

  const total = runs?.length ?? 0;
  const solved = (runs || []).filter((r) => r.solved).length;
  const prs = (runs || []).filter((r) => r.prUrl).length;
  const merged = (runs || []).filter((r) => r.merged).length;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Dashboard"
        description={`${user?.companyName ? user.companyName + ". " : ""}Agents propose, your tests decide, you merge.`}
        actions={
          <LinkButton href="/new" icon="plus">
            Fix a bug
          </LinkButton>
        }
      />

      <Checklist gh={gh} slack={slack} runs={runs} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Runs" value={runs ? total : "–"} />
        <Stat label="Solved" value={runs ? solved : "–"} hint={runs && total ? `${Math.round((solved / total) * 100)}% of your runs` : undefined} />
        <Stat label="Pull requests" value={runs ? prs : "–"} />
        <Stat label="Merged by you" value={runs ? merged : "–"} />
      </div>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <h2 className="text-[15px] font-semibold text-white">Run history</h2>
          <button onClick={load} className="focus-ring inline-flex items-center gap-1.5 rounded px-2 py-1 text-[13px] text-on-surface-variant hover:text-white">
            <Icon name="refresh" size={14} />
            Refresh
          </button>
        </div>
        {error && <ErrorNote className="m-4">{error}</ErrorNote>}
        {!runs ? (
          <div className="flex flex-col gap-2 p-5">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-11" />
            ))}
          </div>
        ) : runs.length === 0 ? (
          <EmptyState
            icon="bug"
            title="No runs yet"
            description="Describe a bug in one of your repositories and PatchLoop will try to fix it. You will see every attempt live."
            action={
              <LinkButton href="/new" icon="plus">
                Fix your first bug
              </LinkButton>
            }
          />
        ) : (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-left text-[13px]" data-testid="runs-table">
                <thead>
                  <tr className="border-b border-border text-[12px] text-on-surface-variant">
                    {["Status", "Problem", "Source", "Tests", "Cost", "Speed", "Safety", "PR", "Started"].map((h) => (
                      <th key={h} scope="col" className="whitespace-nowrap px-4 py-2.5 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.id} className="border-b border-border/60 transition-colors last:border-0 hover:bg-surface-container-low">
                      <td className="px-4 py-3">
                        <StatusChip status={statusOf(r)} />
                      </td>
                      <td className="max-w-[300px] px-4 py-3">
                        <Link href={`/runs/${r.id}`} className="focus-ring block truncate rounded font-medium text-white hover:text-primary" title={title(r, bugs)}>
                          {title(r, bugs)}
                        </Link>
                        <span className="block truncate font-mono text-[11.5px] text-text-subtle">
                          {r.kind === "repo" ? `${r.repo} · ${r.branch}` : "demo bug"}
                          {r.traceId ? ` · ${r.traceId}` : ""}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-on-surface-variant">{r.source || "web"}</td>
                      <td className="px-4 py-3 font-mono text-[12.5px] text-on-surface">{bestTests(r)}</td>
                      <td className="px-4 py-3 font-mono text-[12.5px] text-on-surface-variant" title="Tokens used">{tokens(r)} tok</td>
                      <td className="px-4 py-3 font-mono text-[12.5px] text-on-surface-variant">{fmtMs(r.latencyMs)}</td>
                      <td className="px-4 py-3">
                        {r.safety ? (
                          <span title={`policy ${r.safety.policy}, security ${r.safety.security}, guard ${r.safety.guard}`}>
                            <Badge tone={Object.values(r.safety).every((v) => v === "pass") ? "success" : "warning"} icon="shield-check">
                              {Object.values(r.safety).every((v) => v === "pass") ? "all pass" : "flagged"}
                            </Badge>
                          </span>
                        ) : (
                          <span className="text-text-subtle">–</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {r.merged ? (
                          <Badge tone="info" icon="git-pr">merged</Badge>
                        ) : r.prUrl ? (
                          <a href={r.prUrl} target="_blank" rel="noopener noreferrer" className="focus-ring inline-flex items-center gap-1 rounded text-primary hover:underline">
                            {r.prNumber ? `#${r.prNumber}` : "PR"} <Icon name="external" size={12} />
                          </a>
                        ) : (
                          <span className="text-text-subtle">–</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-on-surface-variant">{when(r.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="divide-y divide-border md:hidden">
              {runs.map((r) => (
                <li key={r.id}>
                  <Link href={`/runs/${r.id}`} className="focus-ring block px-4 py-3.5">
                    <div className="flex items-start justify-between gap-3">
                      <span className="line-clamp-2 text-[14px] font-medium text-white">{title(r, bugs)}</span>
                      <StatusChip status={statusOf(r)} />
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-x-3 font-mono text-[11.5px] text-on-surface-variant">
                      <span>{r.kind === "repo" ? r.repo : "demo bug"}</span>
                      <span>tests {bestTests(r)}</span>
                      <span>{tokens(r)} tok</span>
                      <span>{fmtMs(r.latencyMs)}</span>
                      {r.prNumber ? <span>PR #{r.prNumber}</span> : null}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </div>
  );
}

export default function DashboardClient() {
  return (
    <RequireAuth>
      <DashboardInner />
    </RequireAuth>
  );
}
