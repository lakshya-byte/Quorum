"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { errorMessage, githubApi, tasksApi, type BranchInfo, type GithubStatus, type RepoSummary, type TaskLimits, type TaskType } from "../../_lib/api";
import { TASK_TYPES, TYPE_BY_ID } from "./taskTypes";
import { RequireAuth } from "../../_lib/auth";
import { Badge, Button, Card, EmptyState, ErrorNote, Field, Icon, Input, LinkButton, PageHeader, Skeleton, Stepper, Textarea, cx } from "../../_ui";

const STEPS = ["Repository", "Describe the task", "Review and start"];

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
  const [taskType, setTaskType] = useState<TaskType>("auto");
  const [strict, setStrict] = useState("");
  const [maxWorkers, setMaxWorkers] = useState("");
  const [maxTokens, setMaxTokens] = useState("");
  const [maxWall, setMaxWall] = useState("");
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
      const limits: TaskLimits = {};
      const num = (v: string) => (v.trim() && Number.isFinite(Number(v)) && Number(v) > 0 ? Math.floor(Number(v)) : undefined);
      if (num(maxWorkers)) limits.max_workers = Math.min(8, num(maxWorkers)!);
      if (num(maxTokens)) limits.max_tokens = num(maxTokens);
      if (num(maxWall)) limits.max_wall_s = num(maxWall);
      const ids = strict.split(/[\s,]+/).filter(Boolean);
      const { runId } = await tasksApi.create(repo.fullName, branch, task.trim(), autoPr, { taskType, strict: ids, limits });
      router.push(`/runs/${runId}`);
    } catch (e) {
      setStartErr(errorMessage(e));
      setBusy(false);
    }
  };

  const taskOk = task.trim().length >= 8;
  const info = TYPE_BY_ID[taskType];
  const taskHint = useMemo(() => (task.length > 3800 ? `${4000 - task.length} characters left` : "Plain English is fine. Say what you want, not how. Paste an error message or stack trace if you have one."), [task]);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <PageHeader title="New task" description="Describe a bug, a feature, a refactor or a UI change. PatchLoop spawns a swarm sized to the task, runs it in sandboxes, and opens a pull request only when its own checks pass. You merge." />
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
        <Card className="flex flex-col gap-5 p-5" data-testid="step-task">
          <fieldset>
            <legend className="mb-2 text-[13px] font-medium text-on-surface">What kind of task is it?</legend>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Task type" data-testid="type-chips">
              {TASK_TYPES.map((t) => {
                const on = t.id === taskType;
                return (
                  <label
                    key={t.id}
                    className={cx(
                      "relative inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-primary",
                      on ? "border-primary/60 bg-primary/10 text-white" : "border-border-strong text-on-surface-variant hover:text-white"
                    )}
                  >
                    <input type="radio" name="task-type" value={t.id} checked={on} onChange={() => setTaskType(t.id)} className="sr-only" data-testid={`type-${t.id}`} />
                    <Icon name={t.icon} size={14} className={on ? "text-primary" : ""} />
                    {t.label}
                  </label>
                );
              })}
            </div>
            <p className="mt-3 flex items-start gap-2 rounded-lg border border-border bg-surface-container-low px-3 py-2.5 text-[13px] leading-5 text-on-surface-variant" data-testid="type-how" aria-live="polite">
              <Icon name="shield-check" size={16} className="mt-0.5 text-primary" />
              <span>
                <span className="font-medium text-white">How it is verified: </span>
                {info.how}
              </span>
            </p>
          </fieldset>
          <Field label="What should change?" hint={taskHint}>
            {(p) => (
              <Textarea {...p} value={task} onChange={(e) => setTask(e.target.value)} maxLength={4000} placeholder={info.placeholder} className="min-h-[150px]" data-testid="task-input" />
            )}
          </Field>
          <div>
            <p className="mb-2 text-[12.5px] font-medium text-on-surface-variant">Examples, click to use one</p>
            <div className="flex flex-col gap-2" data-testid="examples">
              {info.examples.map((ex) => (
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
          <details className="group rounded-lg border border-border bg-surface-container-low" data-testid="advanced">
            <summary className="focus-ring flex cursor-pointer list-none items-center justify-between gap-2 rounded-lg px-3.5 py-2.5 text-[13px] font-medium text-white">
              Advanced: strict criteria and limits
              <Icon name="chevron-down" size={15} className="text-on-surface-variant transition-transform group-open:rotate-180" />
            </summary>
            <div className="grid gap-4 border-t border-border p-4 sm:grid-cols-2">
              <Field label="Make these advisory checks hard" hint="Criterion ids from the plan, comma separated, for example ui_vision. A promoted check can then block the pull request." className="sm:col-span-2">
                {(p) => <Input {...p} value={strict} onChange={(e) => setStrict(e.target.value)} placeholder="ui_vision, readability" autoComplete="off" data-testid="strict-input" />}
              </Field>
              <Field label="Max parallel workers" hint="1 to 8. The server enforces its own cap.">
                {(p) => <Input {...p} type="number" min={1} max={8} inputMode="numeric" value={maxWorkers} onChange={(e) => setMaxWorkers(e.target.value)} placeholder="default" data-testid="limit-workers" />}
              </Field>
              <Field label="Max tokens" hint="Run stops at this budget.">
                {(p) => <Input {...p} type="number" min={10000} inputMode="numeric" value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} placeholder="default" />}
              </Field>
              <Field label="Max wall time (seconds)" hint="Run stops at this limit.">
                {(p) => <Input {...p} type="number" min={30} inputMode="numeric" value={maxWall} onChange={(e) => setMaxWall(e.target.value)} placeholder="default" />}
              </Field>
            </div>
          </details>
        </Card>
      )}

      {step === 2 && repo && (
        <Card className="flex flex-col gap-5 p-5" data-testid="step-review">
          <dl className="grid gap-4 sm:grid-cols-[120px_1fr]">
            <dt className="text-[13px] text-on-surface-variant">Repository</dt>
            <dd className="font-mono text-[13.5px] text-white">{repo.fullName}</dd>
            <dt className="text-[13px] text-on-surface-variant">Branch</dt>
            <dd className="font-mono text-[13.5px] text-white">{branch}</dd>
            <dt className="text-[13px] text-on-surface-variant">Task type</dt>
            <dd className="text-[14px] text-white">
              {info.label}
              <span className="mt-1 block text-[12.5px] leading-5 text-on-surface-variant">{info.how}</span>
            </dd>
            <dt className="text-[13px] text-on-surface-variant">Task</dt>
            <dd className="whitespace-pre-wrap text-[14px] leading-6 text-on-surface">{task}</dd>
          </dl>
          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-surface-container-low p-3.5">
            <input type="checkbox" checked={autoPr} onChange={(e) => setAutoPr(e.target.checked)} className="mt-1 h-4 w-4 accent-[#10b981]" />
            <span>
              <span className="block text-[14px] font-medium text-white">Open a pull request when the checks pass</span>
              <span className="block text-[13px] text-on-surface-variant">The branch is named patchloop/…, and nothing is merged until you press Merge.</span>
            </span>
          </label>
          <ul className="grid gap-2 text-[13px] text-on-surface-variant sm:grid-cols-3">
            <li className="flex items-center gap-2"><Icon name="box" size={15} className="text-primary" />Everything runs in sandboxes</li>
            <li className="flex items-center gap-2"><Icon name="flask" size={15} className="text-primary" />Its own checks decide</li>
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
            {busy ? "Starting…" : "Start task"}
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
