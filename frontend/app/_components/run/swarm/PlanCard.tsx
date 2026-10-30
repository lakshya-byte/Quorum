"use client";

import type { Plan } from "../../../_lib/api";
import { typeLabel } from "../../../_lib/swarm";
import { Badge, Card, Icon } from "../../../_ui";

/** The plan: task type (and who chose it), then criteria split into hard gates and advisory checks. */
export default function PlanCard({ plan, finished = false }: { plan: Plan; finished?: boolean }) {
  const hard = plan.criteria.filter((c) => c.hard);
  const adv = plan.criteria.filter((c) => !c.hard);
  const sw = plan.swarm;
  return (
    <Card className="flex flex-col gap-4 p-5" data-testid="plan-card">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold text-white">
          <Icon name="crosshair" size={16} className="text-primary" />
          Plan
        </h2>
        <span data-testid="plan-type">
          <Badge tone="info">{typeLabel(plan.task_type)}</Badge>
        </span>
        <span className="text-[12px] text-on-surface-variant">{plan.task_type_source === "user" ? "chosen by you" : "detected from your description"}</span>
        {sw && (
          <span className="ml-auto text-[12px] text-on-surface-variant">
            {plan.units.length} unit{plan.units.length === 1 ? "" : "s"} · up to {sw.max_parallel ?? "?"} in parallel · {sw.workers_planned ?? "?"} workers planned
          </span>
        )}
      </div>
      {plan.summary && <p className="text-[14px] leading-6 text-on-surface-variant">{plan.summary}</p>}
      <details open={!finished} className="group" data-testid="plan-criteria">
        <summary className="focus-ring mb-3 flex cursor-pointer list-none items-center gap-2 rounded text-[13px] font-medium text-white">
          <Icon name="chevron-down" size={14} className="-rotate-90 text-on-surface-variant transition-transform group-open:rotate-0" />
          {hard.length} hard gates, {adv.length} advisory checks
        </summary>
      <div className="grid gap-4 lg:grid-cols-2">
        <section aria-label="Hard gates">
          <h3 className="mb-2 flex items-center gap-2 text-[12.5px] font-semibold text-white">
            Hard gates <span className="font-normal text-on-surface-variant">all must pass</span>
          </h3>
          <ul className="flex flex-col gap-1.5">
            {hard.map((c) => (
              <li key={c.id} className="flex items-start gap-2 rounded-lg border border-border bg-surface-container-low px-3 py-2">
                <Badge tone="success" className="mt-0.5 shrink-0">
                  hard
                </Badge>
                <span className="min-w-0 text-[13px] leading-5 text-on-surface">
                  {c.description}
                  {c.verifier && <span className="block text-[11.5px] text-text-subtle">checked by: {c.verifier}</span>}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section aria-label="Advisory checks">
          <h3 className="mb-2 flex items-center gap-2 text-[12.5px] font-semibold text-white">
            Advisory checks <span className="font-normal text-on-surface-variant">reported, never block</span>
          </h3>
          {adv.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-3 py-2 text-[13px] text-on-surface-variant">None for this task.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {adv.map((c) => (
                <li key={c.id} className="flex items-start gap-2 rounded-lg border border-border bg-surface-container-low px-3 py-2">
                  <Badge tone="warning" className="mt-0.5 shrink-0">
                    advisory
                  </Badge>
                  <span className="min-w-0 text-[13px] leading-5 text-on-surface">
                    {c.description}
                    {c.verifier && <span className="block text-[11.5px] text-text-subtle">judged by: {c.verifier}</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      </details>
    </Card>
  );
}
