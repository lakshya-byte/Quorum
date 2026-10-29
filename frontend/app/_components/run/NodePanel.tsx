"use client";

import { useEffect, useMemo, useState } from "react";
import type { RunNode } from "../../_lib/api";
import { diffStats, lineDiff } from "../../_lib/diff";
import { nodeTokens, nodeTone } from "../../_lib/runState";
import { fmtMs, shortModel } from "./NodeCard";

type Tab = "diff" | "code" | "tests" | "checks";

function findingText(f: unknown): { title: string; detail?: string } {
  if (typeof f === "string") return { title: f };
  if (f && typeof f === "object") {
    const o = f as Record<string, unknown>;
    const title = [o.severity, o.rule || o.test_id || o.id].filter(Boolean).join(" · ") || "Finding";
    const detail = [o.message || o.issue_text || o.description, o.line != null ? `line ${o.line}` : null].filter(Boolean).join(" — ");
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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const diff = useMemo(
    () => (original != null && node.code != null ? lineDiff(original, node.code) : null),
    [original, node.code]
  );
  const stats = diff ? diffStats(diff) : null;
  const tone = nodeTone(node);
  const toneText = tone === "green" ? "text-primary" : tone === "amber" ? "text-amber-300" : "text-error";
  const findings = node.security?.new_findings || [];

  const tabs: { id: Tab; label: string; hide?: boolean }[] = [
    { id: "diff", label: "Diff", hide: isRoot },
    { id: "code", label: "Code" },
    { id: "tests", label: "Tests" },
    { id: "checks", label: "Policy & security" },
  ];

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50 lg:bg-black/30" onClick={onClose} aria-hidden />
      <aside
        role="dialog"
        aria-label={`Attempt #${node.id}`}
        className="fixed z-50 inset-x-0 bottom-0 top-16 lg:top-0 lg:left-auto lg:w-[560px] bg-[#0b0e15] border-t lg:border-t-0 lg:border-l border-outline-variant/70 shadow-2xl flex flex-col rounded-t-2xl lg:rounded-none"
      >
        <header className="px-4 sm:px-5 py-3.5 border-b border-outline-variant/50 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-[12px] text-on-surface-variant">Attempt #{node.id}</span>
              {node.parent != null && <span className="font-mono text-[11px] text-outline">from #{node.parent}</span>}
              {isBest && (
                <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-primary text-black font-semibold">winner</span>
              )}
            </div>
            <h2 className="mt-1 text-[15px] text-white font-medium leading-snug">{node.idea || (isRoot ? "Original code" : "Candidate fix")}</h2>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-on-surface-variant">
              <span className={toneText}>
                {node.policy?.ok === false ? "not run (policy)" : `${node.passed}/${node.total} tests`}
              </span>
              {node.strategy && <span className="text-secondary">{node.strategy}</span>}
              {shortModel(node.model) && <span>{shortModel(node.model)}</span>}
              {node.latency_ms != null && <span>{fmtMs(node.latency_ms)}</span>}
              {typeof node.score === "number" && <span>score {node.score.toFixed(3)}</span>}
              {nodeTokens(node) > 0 && <span>{nodeTokens(node).toLocaleString()} tok</span>}
            </div>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-lg border border-outline-variant/60 text-on-surface-variant hover:text-white hover:bg-surface-container flex items-center justify-center"
            aria-label="Close"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </header>

        <nav className="px-4 sm:px-5 pt-2 flex gap-1 border-b border-outline-variant/40 overflow-x-auto">
          {tabs
            .filter((t) => !t.hide)
            .map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-3 py-2 text-[12px] font-mono whitespace-nowrap border-b-2 -mb-px transition-colors ${
                  tab === t.id ? "border-primary text-white" : "border-transparent text-on-surface-variant hover:text-white"
                }`}
              >
                {t.label}
                {t.id === "diff" && stats && (
                  <span className="ml-1.5">
                    <span className="text-primary">+{stats.add}</span> <span className="text-error">-{stats.del}</span>
                  </span>
                )}
                {t.id === "checks" && (node.policy?.ok === false || node.security?.ok === false) && (
                  <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-amber-400 align-middle" />
                )}
              </button>
            ))}
        </nav>

        <div className="flex-1 overflow-auto p-4 sm:p-5" data-lenis-prevent>
          {tab === "diff" &&
            (diff ? (
              <div className="rounded-lg bg-[#07090e] border border-outline-variant/50 overflow-x-auto font-mono text-[12px] leading-[1.6] [font-variant-ligatures:none]">
                <div className="px-3 py-1.5 text-[10.5px] text-outline border-b border-outline-variant/40">
                  diff against the original code (#0)
                </div>
                <table className="w-full border-collapse">
                  <tbody>
                    {diff.map((l, i) => (
                      <tr
                        key={i}
                        className={l.kind === "add" ? "bg-primary/12 text-primary" : l.kind === "del" ? "bg-error/12 text-error" : "text-on-surface-variant"}
                      >
                        <td className="select-none text-right pl-2 pr-2 text-outline/70 w-9 align-top">{l.a ?? ""}</td>
                        <td className="select-none text-right pr-3 text-outline/70 w-9 align-top border-r border-outline-variant/30">{l.b ?? ""}</td>
                        <td className="select-none w-5 pl-2 align-top">{l.kind === "add" ? "+" : l.kind === "del" ? "-" : " "}</td>
                        <td className="whitespace-pre pr-3">{l.text || " "}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty text="No code to compare for this attempt." />
            ))}

          {tab === "code" &&
            (node.code ? (
              <pre className="rounded-lg bg-[#07090e] border border-outline-variant/50 p-3 overflow-x-auto font-mono text-[12px] leading-[1.6] text-on-surface whitespace-pre [font-variant-ligatures:none]">
                {node.code}
              </pre>
            ) : (
              <Empty text="No code recorded." />
            ))}

          {tab === "tests" &&
            (node.output ? (
              <pre className="rounded-lg bg-[#07090e] border border-outline-variant/50 p-3 overflow-x-auto font-mono text-[11.5px] leading-[1.55] text-on-surface-variant whitespace-pre">
                {node.output}
              </pre>
            ) : (
              <Empty text="No test output recorded." />
            ))}

          {tab === "checks" && (
            <div className="flex flex-col gap-4">
              <section className="rounded-lg border border-outline-variant/50 bg-surface-container-low p-3.5">
                <h3 className="text-[12px] font-mono uppercase tracking-wider text-on-surface-variant flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[15px]">policy</span> Policy gate
                </h3>
                {!node.policy ? (
                  <p className="mt-2 text-[13px] text-on-surface-variant">Not reported for this engine.</p>
                ) : node.policy.ok ? (
                  <p className="mt-2 text-[13px] text-primary">Passed. No disallowed imports, side effects or files.</p>
                ) : (
                  <ul className="mt-2 space-y-1 text-[13px] text-error">
                    {(node.policy.reasons || ["Blocked"]).map((r) => (
                      <li key={r} className="flex gap-1.5">
                        <span className="material-symbols-outlined text-[15px] mt-0.5">block</span>
                        {r}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section className="rounded-lg border border-outline-variant/50 bg-surface-container-low p-3.5">
                <h3 className="text-[12px] font-mono uppercase tracking-wider text-on-surface-variant flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[15px]">security</span> Security scan
                </h3>
                {!node.security ? (
                  <p className="mt-2 text-[13px] text-on-surface-variant">Not reported for this engine.</p>
                ) : node.security.ok && findings.length === 0 ? (
                  <p className="mt-2 text-[13px] text-primary">Clean. No new findings compared to the original code.</p>
                ) : (
                  <ul className="mt-2 space-y-2">
                    {findings.length === 0 && <li className="text-[13px] text-amber-300">Flagged by the scanner.</li>}
                    {findings.map((f, i) => {
                      const t = findingText(f);
                      return (
                        <li key={i} className="rounded border border-amber-400/30 bg-amber-400/5 px-2.5 py-2">
                          <div className="text-[12px] font-mono text-amber-300">{t.title}</div>
                          {t.detail && <div className="text-[12.5px] text-on-surface-variant mt-0.5">{t.detail}</div>}
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

function Empty({ text }: { text: string }) {
  return <p className="text-[13px] text-on-surface-variant">{text}</p>;
}
