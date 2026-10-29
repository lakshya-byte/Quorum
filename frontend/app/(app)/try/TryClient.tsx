"use client";

import { useEffect, useState } from "react";
import { ApiError, demoApi, errorMessage, type Bug, type CreateRunResponse } from "../../_lib/api";
import { useRunStream } from "../../_lib/useRunStream";
import RunView from "../../_components/run/RunView";
import { CopyCliButton, PrLink } from "../../_components/run/Actions";
import BugPicker from "../_components/BugPicker";
import { Button, Card, ErrorNote, LinkButton, PageHeader, Skeleton } from "../../_ui";
import Link from "next/link";

export default function TryClient() {
  const [bugs, setBugs] = useState<Bug[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [run, setRun] = useState<(CreateRunResponse & { bugId: string }) | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<{ message: string; limited: boolean } | null>(null);

  useEffect(() => {
    demoApi
      .bugs()
      .then((b) => {
        setBugs(b || []);
        if (b?.length) setSelected((s) => s ?? b[0].id);
      })
      .catch((e) => setLoadError(errorMessage(e)));
  }, []);

  const [state, , retry] = useRunStream(run ? demoApi.eventsUrl(run.runId) : null);
  const bug = bugs?.find((b) => b.id === (run?.bugId ?? selected)) ?? null;

  const start = async () => {
    if (!selected || starting) return;
    setStarting(true);
    setStartError(null);
    try {
      const r = await demoApi.create(selected);
      setRun({ ...r, bugId: selected });
    } catch (e) {
      setStartError({ message: errorMessage(e), limited: e instanceof ApiError && e.status === 429 });
    } finally {
      setStarting(false);
    }
  };

  const finished = state.status === "finished" || state.status === "lost";

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Live demo, no account needed"
        title="Watch an agent team fix a bug"
        description="Pick a bug. A triage agent finds the likely cause, parallel proposers try different fixes in isolated sandboxes, a critic keeps the promising ones, and the tests decide. Guest runs use recorded or scripted runs."
      />

      {!run && (
        <Card className="flex flex-col gap-5 p-5">
          <h2 className="text-[15px] font-semibold text-white">Choose a bug</h2>
          {loadError ? (
            <ErrorNote>{loadError}</ErrorNote>
          ) : !bugs ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-[92px] rounded-xl" />
              ))}
            </div>
          ) : (
            <BugPicker bugs={bugs} selected={selected} onSelect={setSelected} />
          )}
          <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center">
            <Button onClick={start} disabled={!selected} loading={starting} icon="play" data-testid="start-run">
              {starting ? "Starting…" : "Run the agent team"}
            </Button>
            <span className="text-[13px] text-on-surface-variant">Guests get 3 runs per hour.</span>
          </div>
          {startError && (
            <ErrorNote tone={startError.limited ? "warning" : "error"}>
              {startError.message}
              {startError.limited && (
                <>
                  {" "}
                  <Link href="/signup" className="underline">
                    Create a free account
                  </Link>{" "}
                  to keep going.
                </>
              )}
            </ErrorNote>
          )}
        </Card>
      )}

      {run && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-[12px] text-on-surface-variant">run {run.runId}</span>
            <Button variant="secondary" size="sm" icon="refresh" onClick={() => setRun(null)} disabled={!finished}>
              Try another bug
            </Button>
          </div>
          <RunView
            state={state}
            bug={bug}
            onRetry={retry}
            solvedActions={
              <>
                {state.prUrl ? (
                  <PrLink url={state.prUrl} />
                ) : (
                  <LinkButton href="/signup" size="sm" icon="git-pr">
                    Sign up to open a PR
                  </LinkButton>
                )}
                <CopyCliButton bugId={run.bugId} />
              </>
            }
          />
        </>
      )}
    </div>
  );
}
