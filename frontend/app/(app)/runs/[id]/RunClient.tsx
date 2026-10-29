"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, errorMessage, runsApi, type Bug, type Run } from "../../../_lib/api";
import { PageSkeleton, RequireAuth } from "../../../_lib/auth";
import { isFinishedRun, useRunStream } from "../../../_lib/useRunStream";
import RunView from "../../../_components/run/RunView";
import { CopyCliButton, OpenPrButton } from "../../../_components/run/Actions";

export function noticeKey(runId: string) {
  return `patchloop:notice:${runId}`;
}

function RunInner({ id }: { id: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [bug, setBug] = useState<Bug | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    runsApi
      .get(id)
      .then((r) => {
        if (cancelled) return;
        setRun(r);
        runsApi
          .bugs()
          .then((bugs) => !cancelled && setBug((bugs || []).find((b) => b.id === r.bugId) ?? null))
          .catch(() => {});
      })
      .catch((e) => !cancelled && setError({ status: e instanceof ApiError ? e.status : 0, message: errorMessage(e) }));
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
  const [state, dispatch, retry] = useRunStream(run && !finished ? runsApi.eventsUrl(id) : null, {
    withCredentials: true,
    snapshot: run && finished ? run : null,
  });
  const onOpened = useCallback((url: string) => dispatch({ kind: "pr", url }), [dispatch]);

  if (error) {
    return (
      <div className="rounded-xl border border-error/40 bg-error/5 p-6 flex flex-col gap-2 items-start">
        <h1 className="text-lg text-white font-semibold">{error.status === 404 ? "Run not found" : "Could not load this run"}</h1>
        <p className="text-[13px] text-on-surface-variant">{error.message}</p>
        <Link href="/dashboard" className="mt-2 text-[13px] text-primary underline">
          Back to dashboard
        </Link>
      </div>
    );
  }
  if (!run) return <PageSkeleton />;

  const bugView = bug ?? { id: run.bugId, title: run.bugId, issue: "", tier: "" };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 font-mono text-[11px] text-on-surface-variant">
        <Link href="/dashboard" className="hover:text-white inline-flex items-center gap-1">
          <span className="material-symbols-outlined text-[15px]">arrow_back</span>
          Dashboard
        </Link>
        <span className="text-outline">/</span>
        <span className="truncate">run {run.id}</span>
      </div>
      <RunView
        state={state}
        bug={bugView}
        notice={notice}
        onRetry={retry}
        solvedActions={
          <>
            <OpenPrButton runId={run.id} prUrl={state.prUrl} onOpened={onOpened} />
            <CopyCliButton bugId={run.bugId} />
          </>
        }
      />
    </div>
  );
}

export default function RunClient({ id }: { id: string }) {
  return (
    <RequireAuth>
      <RunInner id={id} />
    </RequireAuth>
  );
}
