"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { errorMessage, githubApi, tasksApi, type BranchInfo, type GithubStatus, type RepoSummary } from "../../_lib/api";
import { RequireAuth } from "../../_lib/auth";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Icon, Input, LinkButton, PageHeader, Skeleton, Stepper, Textarea, cx } from "../../_ui";

const STEPS = ["Repository", "Describe the problem", "Review and start"];

const EXAMPLES = [
  "Reserving the last unit of an item fails with 'out of stock'.",
  "Invoice totals lose their cents: 19.99 + tax comes out as 24.",
  "word_count returns the wrong number when words are separated by more than one space.",
];

function ago(iso: string) {
  const d = Math.max(0, Date.now() - new Date(iso).getTime());
  const days = Math.floor(d / 86400000);
  return days < 1 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
}

function NewInner() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [gh, setGh] = useState<GithubStatus | null>(null);
  const [ghErr, setGhErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [repos, setRepos] = useState<RepoSummary[] | null>(null);
  const [reposErr, setReposErr] = useState<string | null>(null);
  const [repo, setRepo] = useState<RepoSummary | null>(null);
  const [branches, setBranches] = useState<BranchInfo[] | null>(null);
  const [branch, setBranch] = useState("");
  const [task, setTask] = useState("");
  const [autoPr, setAutoPr] = useState(true);
  const [busy, setBusy] = useState(false);
  const [startErr, setStartErr] = useState<string | null>(null);

  useEffect(() => {
    githubApi
      .status()
      .then(setGh)
      .catch((e) => setGhErr(errorMessage(e)));
  }, []);

  useEffect(() => {
    if (!gh?.connected) return;
    let cancelled = false;
    const t = setTimeout(() => {
      githubApi
        .repos(q)
        .then((r) => !cancelled && (setRepos(r || []), setReposErr(null)))
        .catch((e) => !cancelled && setReposErr(errorMessage(e)));
    }, q ? 220 : 0);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [gh?.connected, q]);

  useEffect(() => {
    if (!repo) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset while the new repo's branches load
    setBranches(null);
    githubApi
      .branches(repo.fullName)
      .then((b) => {
        if (cancelled) return;
        const list = b || [];
        setBranches(list);
        setBranch(list.find((x) => x.default)?.name || repo.defaultBranch || list[0]?.name || "main");
      })
      .catch(() => {
        if (cancelled) return;
        setBranches([]);
        setBranch(repo.defaultBranch || "main");
      });
    return () => {
      cancelled = true;
    };
  }, [repo]);

  const start = async () => {
    if (!repo) return;
    setBusy(true);
    setStartErr(null);
    try {
      const { runId } = await tasksApi.create(repo.fullName, branch, task.trim(), autoPr);
      router.push(`/runs/${runId}`);
    } catch (e) {
      setStartErr(errorMessage(e));
      setBusy(false);
    }
  };

  const taskOk = task.trim().length >= 8;
  const taskHint = useMemo(() => (task.length > 3800 ? `${4000 - task.length} characters left` : "Plain English is fine. Paste an error message or stack trace if you have one."), [task]);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <PageHeader title="Fix a bug" description="Pick a repository, describe what is wrong, and an agent team will try to fix it. You review the pull request." />
      <Stepper steps={STEPS} current={step} onSelect={setStep} />

      {ghErr && <ErrorNote>{ghErr}</ErrorNote>}

      {step === 0 && (
        <Card className="overflow-hidden" data-testid="step-repo">
          {!gh ? (
            <div className="flex flex-col gap-3 p-5">
              <Skeleton className="h-10" />
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          ) : !gh.connected ? (
            <EmptyState
              icon="github"
              title="Connect GitHub first"
              description="PatchLoop needs access to a repository to read the code and open a pull request. You choose which repos to grant. You can also use the offline demo account."
              action={
                <LinkButton href="/integrations" icon="plug">
                  Go to integrations
                </LinkButton>
              }
            />
          ) : (
            <div className="flex flex-col">
              <div className="border-b border-border p-4">
                <label htmlFor="repo-q" className="sr-only">
                  Search repositories
                </label>
                <div className="relative">
                  <Icon name="search" size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-subtle" />
                  <Input id="repo-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search repositories" className="pl-9" autoComplete="off" />
                </div>
                {gh.mode === "demo" && <p className="mt-2 text-[12.5px] text-on-surface-variant">Demo account: three bundled demo repositories, no real GitHub access.</p>}
              </div>
              {reposErr && <ErrorNote className="m-4">{reposErr}</ErrorNote>}
              {!repos ? (
                <div className="flex flex-col gap-2 p-4">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-[68px]" />
                  ))}
                </div>
              ) : repos.length === 0 ? (
                <EmptyState
                  icon="folder"
                  title={q ? "No repositories match" : "No repositories granted yet"}
                  description={q ? "Try a different search." : "Grant PatchLoop access to a repository on GitHub, then come back."}
                />
              ) : (
                <ul role="radiogroup" aria-label="Repositories" className="divide-y divide-border">
                  {repos.map((r) => {
                    const on = repo?.fullName === r.fullName;
                    return (
                      <li key={r.fullName}>
                        <button
                          type="button"
                          role="radio"
                          aria-checked={on}
                          data-repo={r.fullName}
                          onClick={() => setRepo(r)}
                          className={cx("focus-ring flex w-full items-start gap-3 px-4 py-3.5 text-left transition-colors", on ? "bg-primary/5" : "hover:bg-surface-container-low")}
                        >
                          <span className={cx("mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border", on ? "border-primary bg-primary text-[#04120c]" : "border-border-strong")}>
                            {on && <Icon name="check" size={11} strokeWidth={3} />}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-[13.5px] font-medium text-white">{r.fullName}</span>
                              {r.private && <Badge icon="lock">private</Badge>}
                            </span>
                            <span className="mt-0.5 block truncate text-[13px] text-on-surface-variant">{r.description || "No description"}</span>
                          </span>
                          <span className="hidden shrink-0 text-right text-[12px] text-on-surface-variant sm:block">
                            {r.language}
                            <span className="block text-text-subtle">updated {ago(r.updatedAt)}</span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
              {repo && (
                <div className="flex flex-wrap items-end gap-4 border-t border-border bg-surface-container-low px-4 py-4">
                  <Field label="Branch" className="w-full sm:w-64">
                    {(p) =>
                      branches ? (
                        <select
                          {...p}
                          value={branch}
                          onChange={(e) => setBranch(e.target.value)}
                          className="h-10 w-full rounded-lg border border-border-strong bg-surface-container-low px-3 text-[14px] text-white focus-visible:outline-2 focus-visible:outline-primary"
                        >
                          {branches.length === 0 && <option value={branch}>{branch}</option>}
                          {branches.map((b) => (
                            <option key={b.name} value={b.name}>
                              {b.name}
                              {b.default ? " (default)" : ""}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <Skeleton className="h-10" />
                      )
                    }
                  </Field>
                  <p className="pb-2 text-[12.5px] text-on-surface-variant">The agent reads this branch. The fix goes to a new patchloop/ branch, never to {branch || "this branch"}.</p>
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {step === 1 && (
        <Card className="flex flex-col gap-4 p-5" data-testid="step-task">
          <Field label="What is wrong?" hint={taskHint}>
            {(p) => (
              <Textarea
                {...p}
                value={task}
                onChange={(e) => setTask(e.target.value)}
                maxLength={4000}
                placeholder="e.g. Pagination returns the wrong last page when the item count is an exact multiple of the page size."
                className="min-h-[150px]"
                data-testid="task-input"
              />
            )}
          </Field>
          <div>
            <p className="mb-2 text-[12.5px] font-medium text-on-surface-variant">Examples for the demo repositories</p>
            <div className="flex flex-col gap-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => setTask(ex)}
                  className="focus-ring rounded-lg border border-border bg-surface-container-low px-3 py-2 text-left text-[13px] text-on-surface hover:border-border-strong hover:bg-surface-container"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        </Card>
      )}

      {step === 2 && repo && (
        <Card className="flex flex-col gap-5 p-5" data-testid="step-review">
          <dl className="grid gap-4 sm:grid-cols-[120px_1fr]">
            <dt className="text-[13px] text-on-surface-variant">Repository</dt>
            <dd className="font-mono text-[13.5px] text-white">{repo.fullName}</dd>
            <dt className="text-[13px] text-on-surface-variant">Branch</dt>
            <dd className="font-mono text-[13.5px] text-white">{branch}</dd>
            <dt className="text-[13px] text-on-surface-variant">Problem</dt>
            <dd className="whitespace-pre-wrap text-[14px] leading-6 text-on-surface">{task}</dd>
          </dl>
          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-surface-container-low p-3.5">
            <input type="checkbox" checked={autoPr} onChange={(e) => setAutoPr(e.target.checked)} className="mt-1 h-4 w-4 accent-[#10b981]" />
            <span>
              <span className="block text-[14px] font-medium text-white">Open a pull request when the tests pass</span>
              <span className="block text-[13px] text-on-surface-variant">The branch is named patchloop/…, and nothing is merged until you press Merge.</span>
            </span>
          </label>
          <ul className="grid gap-2 text-[13px] text-on-surface-variant sm:grid-cols-3">
            <li className="flex items-center gap-2"><Icon name="box" size={15} className="text-primary" />Candidates run in sandboxes</li>
            <li className="flex items-center gap-2"><Icon name="flask" size={15} className="text-primary" />Your tests decide</li>
            <li className="flex items-center gap-2"><Icon name="lock" size={15} className="text-primary" />Never pushes to {branch}</li>
          </ul>
          {startErr && (
            <ErrorNote>
              {startErr}{" "}
              {/connect github/i.test(startErr) && (
                <Link href="/integrations" className="underline">
                  Open integrations
                </Link>
              )}
            </ErrorNote>
          )}
        </Card>
      )}

      <div className="flex items-center justify-between">
        <Button variant="ghost" icon="arrow-left" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0 || busy}>
          Back
        </Button>
        {step < 2 ? (
          <Button iconRight="arrow-right" onClick={() => setStep((s) => s + 1)} disabled={step === 0 ? !repo : !taskOk} data-testid="next">
            Continue
          </Button>
        ) : (
          <Button icon="play" onClick={start} loading={busy} data-testid="start-task">
            {busy ? "Starting…" : "Start fixing"}
          </Button>
        )}
      </div>
    </div>
  );
}

export default function NewClient() {
  return (
    <RequireAuth>
      <NewInner />
    </RequireAuth>
  );
}
