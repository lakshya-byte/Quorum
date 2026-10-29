"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { RunNode } from "../../_lib/api";
import { diffStats, lineDiff } from "../../_lib/diff";
import { diffFileFromLines, parseUnifiedDiff, type DiffFile } from "../../_lib/unified";
import { nodeTokens, nodeTone } from "../../_lib/runState";
import { Badge, Icon, Tabs } from "../../_ui";
import DiffViewer from "./DiffViewer";
import { fmtMs, shortModel } from "./NodeCard";

type Tab = "diff" | "code" | "tests" | "checks";

function findingText(f: unknown): { title: string; detail?: string } {
  if (typeof f === "string") return { title: f };
  if (f && typeof f === "object") {
    const o = f as Record<string, unknown>;
    const title = [o.severity, o.rule || o.test_id || o.id].filter(Boolean).join(" · ") || "Finding";
    const detail = [o.message || o.issue_text || o.description, o.line != null ? `line ${o.line}` : null].filter(Boolean).join(" · ");
    return { title: String(title), detail: detail || JSON.stringify(o) };
  }
  return { title: String(f) };
}

export default function NodePanel({
  node,
  original,
  isBest,
  onClose,
}: {
  node: RunNode;
  original: string | undefined;
  isBest: boolean;
  onClose: () => void;
}) {
  const isRoot = node.parent == null;
  const [tab, setTab] = useState<Tab>(isRoot ? "code" : "diff");
  const [fileSel, setFileSel] = useState(0);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const files: DiffFile[] = useMemo(() => {
    if (node.diff) {
      const parsed = parseUnifiedDiff(node.diff);
      if (parsed.length) return parsed;
    }
    if (original != null && node.code != null) return [diffFileFromLines("primary file", lineDiff(original, node.code))];
    return [];
  }, [node.diff, node.code, original]);

  const total = files.reduce((a, f) => ({ add: a.add + f.add, del: a.del + f.del }), { add: 0, del: 0 });
  void diffStats;
  const tone = nodeTone(node);
  const toneText = tone === "green" ? "text-primary" : tone === "amber" ? "text-warning" : "text-error";
  const findings = node.security?.new_findings || [];
  const fileEntries = node.files ? Object.entries(node.files) : node.code ? [["code", node.code] as [string, string]] : [];
  const flagged = node.policy?.ok === false || node.security?.ok === false;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/55" onClick={onClose} aria-hidden />
      <aside
        role="dialog"
        aria-label={`Attempt #${node.id}`}
        className="fixed inset-x-0 bottom-0 top-16 z-50 flex flex-col rounded-t-2xl border-t border-border-strong bg-panel shadow-pop lg:left-auto lg:top-0 lg:w-[640px] lg:rounded-none lg:border-l lg:border-t-0"
      >
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[12px] text-on-surface-variant">Attempt #{node.id}</span>
              {node.parent != null && <span className="font-mono text-[11px] text-text-subtle">from #{node.parent}</span>}
              {isBest && <Badge tone="success" icon="trophy">winner</Badge>}
            </div>
            <h2 className="mt-1 text-[16px] font-semibold leading-snug text-white">{node.idea || (isRoot ? "Original code" : "Candidate fix")}</h2>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11.5px] text-on-surface-variant">
              <span className={toneText}>{node.policy?.ok === false ? "not run (policy)" : `${node.passed}/${node.total} tests`}</span>
              {node.strategy && <span className="text-secondary">{node.strategy}</span>}
              {shortModel(node.model) && <span>{shortModel(node.model)}</span>}
              {node.latency_ms != null && <span>{fmtMs(node.latency_ms)}</span>}
              {typeof node.score === "number" && <span>score {node.score.toFixed(3)}</span>}
              {nodeTokens(node) > 0 && <span>{nodeTokens(node).toLocaleString()} tok</span>}
            </div>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            className="focus-ring flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border-strong text-on-surface-variant hover:bg-surface-container hover:text-white"
            aria-label="Close"
          >
            <Icon name="x" size={16} />
          </button>
        </header>

        <Tabs<Tab>
          label="Attempt details"
          value={tab}
          onChange={setTab}
          className="px-3"
          tabs={[
            {
              id: "diff",
              hidden: isRoot,
              label: "Diff",
              badge: files.length ? (
                <span className="font-mono text-[11px]">
                  <span className="text-primary">+{total.add}</span> <span className="text-error">-{total.del}</span>
                </span>
              ) : undefined,
            },
            { id: "code", label: fileEntries.length > 1 ? `Files (${fileEntries.length})` : "Code" },
            { id: "tests", label: "Tests" },
            { id: "checks", label: "Policy & security", badge: flagged ? <span className="h-1.5 w-1.5 rounded-full bg-warning" /> : undefined },
          ]}
        />

        <div className="flex-1 overflow-auto p-5">
          {tab === "diff" &&
            (files.length ? (
              <DiffViewer files={files} caption={files.length > 1 ? `${files.length} files changed in this candidate` : "Changes against the original code"} />
            ) : (
              <p className="text-[13px] text-on-surface-variant">No code to compare for this attempt.</p>
            ))}

          {tab === "code" &&
            (fileEntries.length ? (
              <div className="flex flex-col gap-3">
                {fileEntries.length > 1 && (
                  <div className="flex flex-wrap gap-1.5">
                    {fileEntries.map(([p], i) => (
                      <button
                        key={p}
                        onClick={() => setFileSel(i)}
                        aria-pressed={i === Math.min(fileSel, fileEntries.length - 1)}
                        className={`focus-ring rounded-md border px-2 py-1 font-mono text-[11.5px] ${
                          i === Math.min(fileSel, fileEntries.length - 1) ? "border-primary/50 bg-primary/10 text-white" : "border-border-strong text-on-surface-variant hover:text-white"
                        }`}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                )}
                <pre className="overflow-x-auto whitespace-pre rounded-lg border border-border bg-bg p-3 font-mono text-[12px] leading-[1.6] text-on-surface [font-variant-ligatures:none]">
                  {fileEntries[Math.min(fileSel, fileEntries.length - 1)][1]}
                </pre>
              </div>
            ) : (
              <p className="text-[13px] text-on-surface-variant">No code recorded.</p>
            ))}

          {tab === "tests" &&
            (node.output ? (
              <pre className="overflow-x-auto whitespace-pre rounded-lg border border-border bg-bg p-3 font-mono text-[11.5px] leading-[1.55] text-on-surface-variant">{node.output}</pre>
            ) : (
              <p className="text-[13px] text-on-surface-variant">No test output recorded.</p>
            ))}

          {tab === "checks" && (
            <div className="flex flex-col gap-4">
              <section className="rounded-lg border border-border bg-surface-container-low p-4">
                <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-white">
                  <Icon name="shield" size={15} /> Policy gate
                </h3>
                {!node.policy ? (
                  <p className="mt-2 text-[13px] text-on-surface-variant">Not reported for this engine.</p>
                ) : node.policy.ok ? (
                  <p className="mt-2 text-[13px] text-primary">Passed. No disallowed imports, side effects or files.</p>
                ) : (
                  <ul className="mt-2 space-y-1 text-[13px] text-error">
                    {(node.policy.reasons || ["Blocked"]).map((r) => (
                      <li key={r} className="flex gap-1.5">
                        <Icon name="ban" size={15} className="mt-0.5" />
                        {r}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section className="rounded-lg border border-border bg-surface-container-low p-4">
                <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-white">
                  <Icon name="shield-check" size={15} /> Security scan
                </h3>
                {!node.security ? (
                  <p className="mt-2 text-[13px] text-on-surface-variant">Not reported for this engine.</p>
                ) : node.security.ok && findings.length === 0 ? (
                  <p className="mt-2 text-[13px] text-primary">Clean. No new findings compared to the original code.</p>
                ) : (
                  <ul className="mt-2 space-y-2">
                    {findings.length === 0 && <li className="text-[13px] text-warning">Flagged by the scanner.</li>}
                    {findings.map((f, i) => {
                      const t = findingText(f);
                      return (
                        <li key={i} className="rounded border border-warning/30 bg-warning/5 px-2.5 py-2">
                          <div className="font-mono text-[12px] text-warning">{t.title}</div>
                          {t.detail && <div className="mt-0.5 text-[12.5px] text-on-surface-variant">{t.detail}</div>}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
