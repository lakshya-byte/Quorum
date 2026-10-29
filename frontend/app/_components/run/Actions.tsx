"use client";

import { useState } from "react";
import { errorMessage, runsApi } from "../../_lib/api";

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for non-secure contexts.
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    ta.remove();
    return ok;
  }
}

export function CopyButton({ text, label, className = "" }: { text: string; label: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        if (await copyText(text)) {
          setCopied(true);
          setTimeout(() => setCopied(false), 1800);
        }
      }}
      className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-outline-variant/60 bg-surface-container text-[12.5px] text-white hover:bg-surface-bright transition-colors ${className}`}
    >
      <span className="material-symbols-outlined text-[16px]">{copied ? "check" : "terminal"}</span>
      {copied ? "Copied" : label}
    </button>
  );
}

export function CopyCliButton({ bugId }: { bugId: string }) {
  return <CopyButton text={`patchloop fix ${bugId}`} label="Copy CLI command" />;
}

export function PrLink({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="pr-link"
      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-primary/50 bg-primary/10 text-[12.5px] text-primary hover:bg-primary/20 transition-colors font-medium"
    >
      <span className="material-symbols-outlined text-[16px]">merge</span>
      Pull request {url.match(/\/pull\/(\d+)/)?.[1] ? `#${url.match(/\/pull\/(\d+)/)![1]}` : ""}
      <span className="material-symbols-outlined text-[14px]">open_in_new</span>
    </a>
  );
}

export function OpenPrButton({ runId, prUrl, onOpened }: { runId: string; prUrl: string | null; onOpened: (url: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (prUrl) return <PrLink url={prUrl} />;
  return (
    <div className="flex flex-col items-start sm:items-end gap-1">
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            const { url } = await runsApi.openPr(runId);
            onOpened(url);
          } catch (e) {
            setError(errorMessage(e));
          } finally {
            setBusy(false);
          }
        }}
        className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-primary text-black text-[12.5px] font-semibold shadow-[0_0_18px_rgba(16,185,129,0.35)] hover:bg-[#34d399] disabled:opacity-70 transition-colors"
      >
        <span className={`material-symbols-outlined text-[16px] ${busy ? "animate-spin" : ""}`}>{busy ? "progress_activity" : "call_merge"}</span>
        {busy ? "Opening pull request…" : "Open pull request"}
      </button>
      {error && <span className="text-[12px] text-error">{error}</span>}
    </div>
  );
}
