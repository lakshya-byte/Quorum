"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { errorMessage, runsApi, type Bug, type Engine, type Run } from "../../_lib/api";
import { RequireAuth, useAuth } from "../../_lib/auth";
import { isFinishedRun } from "../../_lib/useRunStream";
import { fmtMs } from "../../_components/run/NodeCard";
import { groupByTier } from "../_components/BugPicker";
import { noticeKey } from "../runs/[id]/RunClient";

function runStatus(r: Run): { label: string; cls: string } {
  if (!isFinishedRun(r)) return { label: "running", cls: "text-primary border-primary/40 bg-primary/10" };
  if (r.solved) return { label: "solved", cls: "text-primary border-primary/40 bg-primary/10" };
  if ((r.status || "").toLowerCase() === "failed") return { label: "failed", cls: "text-error border-error/40 bg-error/10" };
  return { label: "unsolved", cls: "text-amber-300 border-amber-400/40 bg-amber-400/10" };
}

function bestTests(r: Run): string {
  const nodes = r.nodes || [];
  const best = r.bestNodeId != null ? nodes.find((n) => n.id === r.bestNodeId) : undefined;
  const pick = best ?? [...nodes].sort((a, b) => b.passed / (b.total || 1) - a.passed / (a.total || 1))[0];
  return pick ? `${pick.passed}/${pick.total}` : "–";
}

function tokens(r: Run): string {
  const u = r.usage;
  const t = (u?.prompt_tokens || 0) + (u?.completion_tokens || 0);
  return t ? t.toLocaleString() : "–";
}

function NewFix({ bugs }: { bugs: Bug[] | null }) {
  const router = useRouter();
  const [bugId, setBugId] = useState("");
  const [engine, setEngine] = useState<Engine>("graph");
  const [replay, setReplay] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const effectiveBug = bugId || bugs?.[0]?.id || "";

  const start = async () => {
    if (!effectiveBug) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await runsApi.create(effectiveBug, engine, replay);
      if (r.notice) {
        setNotice(r.notice);
        try {
          sessionStorage.setItem(noticeKey(r.runId), r.notice);
        } catch {
          // storage unavailable
        }
      }
      router.push(`/runs/${r.runId}`);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-outline-variant/60 bg-[#0b0e15] p-4 sm:p-5 flex flex-col gap-4">
      <h2 className="text-[13px] font-mono uppercase tracking-wider text-on-surface-variant flex items-center gap-1.5">
        <span className="material-symbols-outlined text-[16px] text-primary">add_circle</span>
        New fix
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_auto] gap-3 md:items-end">
        <label className="flex flex-col gap-1.5">
          <span className="text-[11px] font-mono text-on-surface-variant">Bug</span>
          <select
            value={effectiveBug}
            onChange={(e) => setBugId(e.target.value)}
            disabled={!bugs}
            data-testid="bug-select"
            className="w-full px-3 py-2.5 bg-surface-container-low border border-white/10 rounded-lg text-[13px] text-on-surface focus:outline-none focus:border-primary"
          >
            {!bugs && <option>Loading bugs…</option>}
            {bugs &&
              groupByTier(bugs).map(([tier, list]) => (
                <optgroup key={tier} label={tier}>
                  {list.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.title}
                    </option>
                  ))}
                </optgroup>
              ))}
          </select>
        </label>
        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] font-mono text-on-surface-variant">Engine</span>
          <div className="inline-flex rounded-lg border border-white/10 p-0.5 bg-surface-container-low" role="radiogroup">
            {(
              [
                ["graph", "Agent team"],
                ["loop", "Loop"],
              ] as [Engine, string][]
            ).map(([v, l]) => (
              <button
                key={v}
                type="button"
                role="radio"
                aria-checked={engine === v}
                onClick={() => setEngine(v)}
                className={`px-3 py-2 rounded-md text-[12.5px] transition-colors ${engine === v ? "bg-surface-bright text-white" : "text-on-surface-variant hover:text-white"}`}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        <label className="flex items-center gap-2 h-[42px] px-3 rounded-lg border border-white/10 bg-surface-container-low cursor-pointer select-none">
          <input type="checkbox" checked={replay} onChange={(e) => setReplay(e.target.checked)} className="accent-[#10b981] w-4 h-4" />
          <span className="text-[12.5px] text-on-surface">Replay a recorded run</span>
        </label>
      </div>
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <button
          onClick={start}
          disabled={busy || !effectiveBug}
          data-testid="new-fix"
          className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-primary text-black text-[13.5px] font-semibold hover:bg-[#34d399] disabled:opacity-60"
        >
          <span className={`material-symbols-outlined text-[18px] ${busy ? "animate-spin" : ""}`}>{busy ? "progress_activity" : "play_arrow"}</span>
          {busy ? "Starting…" : "Start fix"}
        </button>
        <span className="text-[12px] text-on-surface-variant">
          {engine === "graph" ? "Triage, parallel proposers, critic and reviewer, with guardrails." : "Single-agent loop (older engine)."}
        </span>
      </div>
      {notice && <p className="text-[13px] text-secondary">{notice}</p>}
      {error && <p className="text-[13px] text-error">{error}</p>}
    </section>
  );
}

function DashboardInner() {
  const { user } = useAuth();
  const [bugs, setBugs] = useState<Bug[] | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
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
    runsApi
      .bugs()
      .then((b) => setBugs(b || []))
      .catch((e) => setError(errorMessage(e)));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    load();
  }, [load]);

  const anyRunning = (runs || []).some((r) => !isFinishedRun(r));
  useEffect(() => {
    if (!anyRunning) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [anyRunning, load]);

  const bugTitle = (id: string) => bugs?.find((b) => b.id === id)?.title ?? id;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl sm:text-3xl text-white font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-[13.5px] text-on-surface-variant">
          {user?.companyName ? `${user.companyName} · ` : ""}Your fix runs. Agents propose; tests decide; you merge.
        </p>
      </div>

      <NewFix bugs={bugs} />

      <section className="rounded-xl border border-outline-variant/60 bg-[#0b0e15] overflow-hidden">
        <div className="px-4 sm:px-5 py-3 border-b border-outline-variant/50 flex items-center justify-between">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-on-surface-variant">My runs</h2>
          <button onClick={load} className="text-[12px] text-on-surface-variant hover:text-white inline-flex items-center gap-1">
            <span className="material-symbols-outlined text-[15px]">refresh</span>
            Refresh
          </button>
        </div>
        {error && <p className="px-5 py-3 text-[13px] text-error">{error}</p>}
        {!runs ? (
          <div className="p-5 flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-10 rounded bg-surface-container-low animate-pulse" />
            ))}
          </div>
        ) : runs.length === 0 ? (
          <p className="px-5 py-10 text-center text-[13px] text-on-surface-variant">No runs yet. Start one above.</p>
        ) : (
          <>
            {/* desktop table */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead className="font-mono text-[10.5px] uppercase tracking-wider text-on-surface-variant">
                  <tr className="border-b border-outline-variant/40">
                    {["Status", "Bug", "Engine", "Tests", "Tokens", "Latency", "PR", "Started"].map((h) => (
                      <th key={h} className="px-4 py-2.5 font-normal">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => {
                    const s = runStatus(r);
                    return (
                      <tr key={r.id} className="border-b border-outline-variant/25 hover:bg-surface-container-low/60">
                        <td className="px-4 py-2.5">
                          <span className={`inline-flex px-2 py-0.5 rounded-full border font-mono text-[10.5px] ${s.cls}`}>{s.label}</span>
                        </td>
                        <td className="px-4 py-2.5">
                          <Link href={`/runs/${r.id}`} className="text-white hover:text-primary font-mono text-[12.5px]">
                            {bugTitle(r.bugId)}
                          </Link>
                        </td>
                        <td className="px-4 py-2.5 font-mono text-[12px] text-on-surface-variant">
                          {r.engine === "graph" ? "agent team" : r.engine} · {r.mode}
                        </td>
                        <td className="px-4 py-2.5 font-mono text-[12px] text-on-surface">{bestTests(r)}</td>
                        <td className="px-4 py-2.5 font-mono text-[12px] text-on-surface-variant">{tokens(r)}</td>
                        <td className="px-4 py-2.5 font-mono text-[12px] text-on-surface-variant">{fmtMs(r.latencyMs)}</td>
                        <td className="px-4 py-2.5">
                          {r.prUrl ? (
                            <a href={r.prUrl} target="_blank" rel="noopener noreferrer" className="text-primary text-[12px] inline-flex items-center gap-1">
                              <span className="material-symbols-outlined text-[14px]">merge</span>PR
                            </a>
                          ) : (
                            <span className="text-outline">–</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 font-mono text-[11.5px] text-on-surface-variant whitespace-nowrap">
                          {new Date(r.createdAt).toLocaleString()}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {/* mobile cards */}
            <ul className="md:hidden divide-y divide-outline-variant/30">
              {runs.map((r) => {
                const s = runStatus(r);
                return (
                  <li key={r.id}>
                    <Link href={`/runs/${r.id}`} className="block px-4 py-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-[12.5px] text-white truncate">{bugTitle(r.bugId)}</span>
                        <span className={`shrink-0 px-2 py-0.5 rounded-full border font-mono text-[10.5px] ${s.cls}`}>{s.label}</span>
                      </div>
                      <div className="mt-1 font-mono text-[11px] text-on-surface-variant">
                        {r.engine} · tests {bestTests(r)} · {tokens(r)} tok · {fmtMs(r.latencyMs)}
                        {r.prUrl ? " · PR" : ""}
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </section>
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
