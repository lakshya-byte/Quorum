"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, demoApi, errorMessage, type Bug, type CreateRunResponse } from "../../_lib/api";
import { useRunStream } from "../../_lib/useRunStream";
import RunView from "../../_components/run/RunView";
import { CopyCliButton, PrLink } from "../../_components/run/Actions";
import BugPicker from "../_components/BugPicker";

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
      <div className="flex flex-col gap-2">
        <div className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-primary">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          Live demo · no account needed
        </div>
        <h1 className="text-2xl sm:text-3xl text-white font-semibold tracking-tight">Watch an agent team fix a bug</h1>
        <p className="text-[14px] text-on-surface-variant max-w-3xl leading-relaxed">
          Pick a bug. A triage agent finds the cause, parallel proposers try different fixes in isolated sandboxes, a critic
          keeps the promising ones, and the tests decide what is good. Guardrails and a policy gate check every step. Guest runs
          use recorded or scripted runs (replay/fake mode).
        </p>
      </div>

      {!run && (
        <section className="rounded-xl border border-outline-variant/60 bg-[#0b0e15] p-4 sm:p-5 flex flex-col gap-4">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-on-surface-variant">1 · Choose a bug</h2>
          {loadError ? (
            <p className="text-[13px] text-error">{loadError}</p>
          ) : !bugs ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-[86px] rounded-xl bg-surface-container-low animate-pulse" />
              ))}
            </div>
          ) : (
            <BugPicker bugs={bugs} selected={selected} onSelect={setSelected} />
          )}
          <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-2 border-t border-outline-variant/40">
            <button
              onClick={start}
              disabled={!selected || starting}
              data-testid="start-run"
              className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-primary text-black text-[14px] font-semibold shadow-[0_0_24px_rgba(16,185,129,0.35)] hover:bg-[#34d399] disabled:opacity-60 transition-colors"
            >
              <span className={`material-symbols-outlined text-[18px] ${starting ? "animate-spin" : ""}`}>
                {starting ? "progress_activity" : "play_arrow"}
              </span>
              {starting ? "Starting…" : "Run the agent team"}
            </button>
            <span className="text-[12px] text-on-surface-variant">Guests get 3 runs per hour.</span>
          </div>
          {startError && (
            <div className={`rounded-lg border px-3.5 py-2.5 text-[13px] ${startError.limited ? "border-amber-400/40 bg-amber-400/5 text-amber-200" : "border-error/40 bg-error/5 text-error"}`}>
              {startError.message}
              {startError.limited && (
                <>
                  {" "}
                  <Link href="/signup" className="underline text-primary">
                    Create a free account
                  </Link>{" "}
                  to keep going.
                </>
              )}
            </div>
          )}
        </section>
      )}

      {run && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-[11px] text-on-surface-variant">run {run.runId}</span>
            <button
              onClick={() => setRun(null)}
              disabled={!finished}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-outline-variant/60 text-[12.5px] text-on-surface-variant hover:text-white hover:bg-surface-container disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[16px]">restart_alt</span>
              Try another bug
            </button>
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
                  <Link
                    href="/signup"
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-primary text-black text-[12.5px] font-semibold hover:bg-[#34d399]"
                  >
                    <span className="material-symbols-outlined text-[16px]">call_merge</span>
                    Sign up to open a PR
                  </Link>
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
