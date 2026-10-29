"use client";

import { useState } from "react";
import { errorMessage, runsApi } from "../../_lib/api";
import { Button, Icon, LinkButton } from "../../_ui";

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

export function CopyButton({ text, label, icon = "copy", variant = "secondary" }: { text: string; label: string; icon?: string; variant?: "secondary" | "ghost" }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant={variant}
      size="sm"
      icon={copied ? "check" : icon}
      onClick={async () => {
        if (await copyText(text)) {
          setCopied(true);
          setTimeout(() => setCopied(false), 1800);
        }
      }}
    >
      {copied ? "Copied" : label}
    </Button>
  );
}

export function CopyCliButton({ bugId }: { bugId: string }) {
  return <CopyButton text={`patchloop fix ${bugId}`} label="Copy CLI command" icon="terminal" />;
}

export function PrLink({ url }: { url: string }) {
  const n = url.match(/\/pull\/(\d+)/)?.[1];
  return (
    <LinkButton href={url} external variant="secondary" size="sm" icon="git-pr" data-testid="pr-link">
      Pull request {n ? `#${n}` : ""}
      <Icon name="external" size={13} />
    </LinkButton>
  );
}

export function OpenPrButton({ runId, prUrl, onOpened }: { runId: string; prUrl: string | null; onOpened: (url: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (prUrl) return <PrLink url={prUrl} />;
  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <Button
        size="sm"
        icon="git-pr"
        loading={busy}
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
      >
        {busy ? "Opening pull request…" : "Open pull request"}
      </Button>
      {error && <span className="text-[12px] text-error">{error}</span>}
    </div>
  );
}
