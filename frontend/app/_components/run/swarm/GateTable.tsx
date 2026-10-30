"use client";

import { useState } from "react";
import type { CriterionStatus, PlanCriterion, VerifyResultRow } from "../../../_lib/api";
import type { RunState } from "../../../_lib/runState";
import { gateRows, hardCount, type SwarmState } from "../../../_lib/swarm";
import { Badge, Icon, cx, type Tone } from "../../../_ui";

const STATUS: Record<CriterionStatus | "pending", { tone: Tone; label: string; icon: string }> = {
  pass: { tone: "success", label: "pass", icon: "check-circle" },
  fail: { tone: "danger", label: "fail", icon: "x-circle" },
  skip: { tone: "neutral", label: "skip", icon: "ban" },
  advisory: { tone: "warning", label: "advisory", icon: "info" },
  pending: { tone: "neutral", label: "not run yet", icon: "clock" },
};

function StatusPill({ status }: { status: CriterionStatus | "pending" }) {
  const s = STATUS[status];
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {s.label}
    </Badge>
  );
}

type Row = { criterion: PlanCriterion; result: VerifyResultRow | null };

function rowsFor(w: SwarmState, round: number | null): Row[] {
  if (round == null || round === w.verifies[w.verifies.length - 1]?.round) return gateRows(w);
  const v = w.verifies.find((x) => x.round === round);
  if (!v) return gateRows(w);
  const plan = w.plan?.criteria || [];
  const by = new Map(v.results.map((r) => [r.criterion_id, r]));
  return plan.map((c) => ({ criterion: c, result: by.get(c.id) ?? null }));
}

/** Verification gate table: one row per criterion, per-round history above it. */
export default function GateTable({ state }: { state: RunState }) {
  const w = state.swarm;
  const rounds = w.verifies;
  const [picked, setPicked] = useState<number | null>(null);
  const round = picked ?? rounds[rounds.length - 1]?.round ?? null;
  const rows = rowsFor(w, round);
  if (rows.length === 0 || (rounds.length === 0 && !w.saved?.criteriaSummary?.results?.length)) return null;
  const hc = hardCount(w);
  const cur = rounds.find((r) => r.round === round);
  const hardRows = rows.filter((r) => r.criterion.hard);
  const hardPass = cur ? hardRows.filter((r) => r.result?.status === "pass").length : hc?.pass;
  const hardTotal = cur ? hardRows.length : hc?.total;
  // hard gates first, failures first inside each group
  const order = (r: Row) => (r.result?.status === "fail" ? 0 : r.result ? 1 : 2);
  const sorted = [...rows].sort((a, b) => Number(b.criterion.hard) - Number(a.criterion.hard) || order(a) - order(b));

  return (
    <section aria-labelledby="gates-h" className="flex flex-col gap-3" data-testid="gate-table">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="gates-h" className="flex items-center gap-2 text-[15px] font-semibold text-white">
          <Icon name="shield-check" size={16} className="text-primary" />
          Verification gates
        </h2>
        {hardTotal != null && hardPass != null && (
          <p className="text-[13px] text-on-surface-variant" data-testid="hard-count">
            <span className={cx("font-semibold tabular-nums", hardPass === hardTotal ? "text-primary" : "text-warning")}>
              {hardPass}/{hardTotal}
            </span>{" "}
            hard gates passed
          </p>
        )}
      </div>

      {rounds.length > 1 && (
        <div role="group" aria-label="Verification rounds" className="flex flex-wrap gap-2" data-testid="rounds">
          {rounds.map((r) => (
            <button
              key={r.round}
              type="button"
              aria-pressed={r.round === round}
              onClick={() => setPicked(r.round)}
              className={cx("focus-ring inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12.5px]", r.round === round ? "border-primary/50 bg-primary/10 text-white" : "border-border-strong text-on-surface-variant hover:text-white")}
            >
              Round {r.round}
              <span className={r.hard_pass ? "text-primary" : "text-error"}>{r.hard_pass ? "all hard gates pass" : `${r.results.filter((x) => x.hard && x.status === "fail").length} failing`}</span>
            </button>
          ))}
        </div>
      )}

      <div className="hidden overflow-hidden rounded-xl border border-border bg-panel md:block">
        <table className="w-full text-left text-[13px]">
          <caption className="sr-only">Each criterion with its type, status and detail</caption>
          <thead>
            <tr className="border-b border-border text-[12px] text-on-surface-variant">
              <th scope="col" className="px-4 py-2.5 font-medium">Criterion</th>
              <th scope="col" className="w-[92px] px-3 py-2.5 font-medium">Type</th>
              <th scope="col" className="w-[112px] px-3 py-2.5 font-medium">Result</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(({ criterion: c, result: r }) => (
              <tr key={c.id} data-criterion={c.id} data-status={r?.status || "pending"} className={cx("border-b border-border/60 align-top last:border-0", r?.status === "fail" && "bg-error/5")}>
                <td className="px-4 py-2.5 text-on-surface">
                  {c.description}
                  <span className="block font-mono text-[11px] text-text-subtle">{c.kind}</span>
                </td>
                <td className="px-3 py-2.5">{c.hard ? <Badge tone="success">hard</Badge> : <Badge tone="warning">advisory</Badge>}</td>
                <td className="px-3 py-2.5">
                  <StatusPill status={r?.status || "pending"} />
                  {r?.score != null && <span className="ml-1.5 font-mono text-[11.5px] text-on-surface-variant">{r.score.toFixed(2)}</span>}
                </td>
                <td className="px-4 py-2.5 text-on-surface-variant [overflow-wrap:anywhere]">{r?.detail || (r ? "" : "Runs at the verification step.")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="flex flex-col gap-2 md:hidden">
        {sorted.map(({ criterion: c, result: r }) => (
          <li key={c.id} data-criterion={c.id} data-status={r?.status || "pending"} className={cx("rounded-xl border p-3.5", r?.status === "fail" ? "border-error/40 bg-error/5" : "border-border bg-panel")}>
            <div className="flex flex-wrap items-center gap-1.5">
              {c.hard ? <Badge tone="success">hard</Badge> : <Badge tone="warning">advisory</Badge>}
              <StatusPill status={r?.status || "pending"} />
              {r?.score != null && <span className="font-mono text-[11.5px] text-on-surface-variant">{r.score.toFixed(2)}</span>}
            </div>
            <p className="mt-2 text-[13px] leading-5 text-on-surface">{c.description}</p>
            {r?.detail && <p className="mt-1 text-[12.5px] leading-5 text-on-surface-variant [overflow-wrap:anywhere]">{r.detail}</p>}
          </li>
        ))}
      </ul>
      <p className="text-[12px] text-text-subtle">Plain code decides the hard gates. Advisory rows are model judgements: shown for you, never used to block or approve.</p>
    </section>
  );
}
