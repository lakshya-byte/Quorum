"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, errorMessage, runsApi, slackApi, type Bug, type Run } from "../../../_lib/api";
import { PageSkeleton, RequireAuth } from "../../../_lib/auth";
import { isFinishedRun, useRunStream } from "../../../_lib/useRunStream";
import RunView from "../../../_components/run/RunView";
import { CopyCliButton, OpenPrButton } from "../../../_components/run/Actions";
import { Icon, LinkButton } from "../../../_ui";

export function noticeKey(runId: string) {
  return `patchloop:notice:${runId}`;
}

function RunInner({ id }: { id: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [bug, setBug] = useState<Bug | null>(null);
  const [slack, setSlack] = useState<boolean | null>(null);
  const [slackSent, setSlackSent] = useState<boolean | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    runsApi
      .get(id)
      .then((r) => {
        if (cancelled) return;
        setRun(r);
        if (r.kind !== "repo" && r.bugId) {
          runsApi
            .bugs()
            .then((bugs) => !cancelled && setBug((bugs || []).find((b) => b.id === r.bugId) ?? null))
            .catch(() => {});
        }
      })
      .catch((e) => !cancelled && setError({ status: e instanceof ApiError ? e.status : 0, message: errorMessage(e) }));
    slackApi
      .get()
      .then((s) => !cancelled && setSlack(!!s.configured))
      .catch(() => {});
    try {
      const n = sessionStorage.getItem(noticeKey(id));
      // eslint-disable-next-line react-hooks/set-state-in-effect -- read once from browser storage
      if (n) setNotice(n);
    } catch {
      // storage unavailable
    }
    return () => {
      cancelled = true;
    };
  }, [id]);

  const finished = run ? isFinishedRun(run) : false;
  // A finished needs_input run replays its stream once so the planner's questions can be shown again.
  const replay = !!run && finished && run.outcome === "needs_input";
  const [state, dispatch, retry] = useRunStream(run && (!finished || replay) ? runsApi.eventsUrl(id) : null, {
    withCredentials: true,
    snapshot: run && finished && !replay ? run : null,
  });
  // The backend marks run.slackSent a moment after the run finished: look again, without touching the live view.
  const streamDone = state.status === "finished";
  useEffect(() => {
    if (!streamDone) return;
    let cancelled = false;
    const look = () =>
      runsApi
        .get(id)
        .then((r) => !cancelled && setSlackSent(!!r.slackSent))
        .catch(() => {});
    const timers = [setTimeout(look, 600), setTimeout(look, 2500), setTimeout(look, 6000)];
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, [streamDone, id]);
  const onOpened = useCallback((url: string) => dispatch({ kind: "pr", url }), [dispatch]);

  if (error) {
    return (
      <div className="flex flex-col items-start gap-2 rounded-xl border border-error/40 bg-error/5 p-6">
        <h1 className="text-lg font-semibold text-white">{error.status === 404 ? "Run not found" : "Could not load this run"}</h1>
        <p className="text-[14px] text-on-surface-variant">{error.message}</p>
        <LinkButton href="/dashboard" variant="secondary" size="sm" icon="arrow-left" className="mt-2">
          Back to dashboard
        </LinkButton>
      </div>
    );
  }
  if (!run) return <PageSkeleton />;

  const isRepo = run.kind === "repo";
  const bugView = isRepo ? null : (bug ?? { id: run.bugId, title: run.bugId, issue: "", tier: "" });

  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-[13px] text-on-surface-variant">
        <Link href="/dashboard" className="focus-ring inline-flex items-center gap-1 rounded hover:text-white">
          <Icon name="arrow-left" size={14} />
          Dashboard
        </Link>
        <span className="text-text-subtle">/</span>
        <span className="truncate font-mono text-[12px]">run {run.id}</span>
        {run.parentRunId && (
          <>
            <span className="text-text-subtle">·</span>
            <Link href={`/runs/${run.parentRunId}`} className="focus-ring rounded text-primary underline">
              follow-up of {run.parentRunId.slice(0, 8)}
            </Link>
          </>
        )}
      </nav>
      <RunView
        state={state}
        bug={bugView}
        run={run}
        notice={notice}
        onRetry={retry}
        slackConfigured={slack}
        slackSent={slackSent ?? (run.slackSent ? true : null)}
        solvedActions={
          isRepo ? null : (
            <>
              <OpenPrButton runId={run.id} prUrl={state.prUrl} onOpened={onOpened} />
              <CopyCliButton bugId={run.bugId} />
            </>
          )
        }
      />
    </div>
  );
}

export default function RunClient({ id }: { id: string }) {
  return (
    <RequireAuth>
      <RunInner key={id} id={id} />
    </RequireAuth>
  );
}
