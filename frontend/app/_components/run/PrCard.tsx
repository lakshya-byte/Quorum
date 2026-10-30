"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { errorMessage, prApi, type Outcome, type PrInfo } from "../../_lib/api";
import type { PrEvent } from "../../_lib/runState";
import { Badge, Button, Card, ErrorNote, Icon, LinkButton, Textarea, useToast, type Tone } from "../../_ui";

const CHECK_TONE: Record<string, { tone: Tone; label: string }> = {
  success: { tone: "success", label: "Checks passing" },
  failure: { tone: "danger", label: "Checks failing" },
  pending: { tone: "warning", label: "Checks running" },
  none: { tone: "neutral", label: "No CI configured" },
};

export default function PrCard({ runId, pr, repo, onFollowup, outcome, unverified }: { runId: string; pr: PrEvent; repo?: string; onFollowup?: (newRunId: string) => void; outcome?: Outcome | null; unverified?: string[] }) {
  const router = useRouter();
  const { toast } = useToast();
  const [info, setInfo] = useState<PrInfo | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [merging, setMerging] = useState(false);
  const [mergeErr, setMergeErr] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [showChanges, setShowChanges] = useState(false);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sendErr, setSendErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setInfo(await prApi.get(runId));
      setLoadErr(null);
    } catch (e) {
      setLoadErr(errorMessage(e));
    }
  }, [runId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch PR status when the PR appears
    load();
  }, [load, pr.url]);

  const pending = info?.checks.state === "pending";
  useEffect(() => {
    if (!pending) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [pending, load]);

  const merged = info?.merged || (info?.state === "merged" ? {} : null);
  const check = info ? CHECK_TONE[info.checks.state] : null;
  const number = info?.number ?? pr.number;
  const url = info?.url || pr.url;

  const doMerge = async () => {
    setMerging(true);
    setMergeErr(null);
    try {
      const r = await prApi.merge(runId, "squash");
      if (r.warning) setWarning(r.warning);
      toast("Merged. The change is now on the base branch.", "success");
      setConfirm(false);
      await load();
    } catch (e) {
      setMergeErr(errorMessage(e));
    } finally {
      setMerging(false);
    }
  };

  const sendChanges = async () => {
    if (!message.trim()) return;
    setSending(true);
    setSendErr(null);
    try {
      const r = await prApi.followup(runId, message.trim());
      toast("Sent. PatchLoop will push one new commit to the same branch.", "success");
      setMessage("");
      setShowChanges(false);
      if (onFollowup) onFollowup(r.runId);
      else router.push(`/runs/${r.runId}`);
    } catch (e) {
      setSendErr(errorMessage(e));
    } finally {
      setSending(false);
    }
  };

  return (
    <Card className="overflow-hidden" data-testid="pr-card">
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${merged ? "border-secondary/40 bg-secondary/10 text-secondary" : "border-primary/40 bg-primary/10 text-primary"}`}>
              <Icon name="git-pr" size={18} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-[15px] font-semibold text-white">
                  {merged ? "Pull request merged" : pr.updated ? "Pull request updated" : "Pull request ready for review"}
                </h3>
                {pr.fake && <Badge tone="warning" title="Demo mode: no real pull request exists">demo PR</Badge>}
                {outcome === "partial" && <Badge tone="warning" icon="alert">Partial</Badge>}
                {outcome === "complete" && <Badge tone="success" icon="check-circle">Complete</Badge>}
                {pr.commits ? <Badge title="One commit per unit, so you can review incrementally">{pr.commits} commits</Badge> : null}
              </div>
              <p className="mt-0.5 truncate font-mono text-[12.5px] text-on-surface-variant">
                {repo ? `${repo} ` : ""}
                {number ? `#${number}` : ""}
                {pr.branch ? ` · ${pr.branch}` : ""}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {check && <Badge tone={check.tone} icon={info?.checks.state === "success" ? "check" : info?.checks.state === "failure" ? "x" : "clock"}>{check.label}</Badge>}
            {info && info.mergeable === false && <Badge tone="danger">conflicts</Badge>}
          </div>
        </div>

        {info?.checks.failing && info.checks.failing.length > 0 && (
          <ErrorNote>Failing: {info.checks.failing.join(", ")}</ErrorNote>
        )}
        {loadErr && !info && <ErrorNote tone="warning">Could not load live PR status ({loadErr}). The pull request is still available on GitHub.</ErrorNote>}
        {info?.checks.state === "none" && !merged && (
          <ErrorNote tone="warning">
            This repository has no CI checks, so nothing but PatchLoop&apos;s own tests has verified the change. Review the diff before you merge.
          </ErrorNote>
        )}
        {warning && <ErrorNote tone="warning">{warning}</ErrorNote>}
        {outcome === "partial" && !merged && (
          <ErrorNote tone="warning">
            <span data-testid="partial-warning">
              This result is partial: every hard gate passed, but not everything you asked for could be proven by a check.
              {unverified && unverified.length > 0 ? ` Not verified: ${unverified.join(" ")}` : ""} Read the diff before you merge.
            </span>
          </ErrorNote>
        )}

        {merged ? (
          <p className="text-[13.5px] text-on-surface-variant" data-testid="merged-note">
            Merged{merged.by ? ` by ${merged.by}` : ""}
            {merged.at ? ` on ${new Date(merged.at).toLocaleString()}` : ""}. PatchLoop never merges on its own; a person did this.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <LinkButton href={url} external variant="secondary" icon="external">
                {pr.fake ? "Open demo PR" : "Review on GitHub"}
              </LinkButton>
              {!confirm ? (
                <Button
                  onClick={() => setConfirm(true)}
                  disabled={!info || !info.mergeAllowed}
                  icon="git-pr"
                  data-testid="merge-btn"
                  aria-describedby={info && !info.mergeAllowed ? "merge-reason" : undefined}
                >
                  Merge pull request
                </Button>
              ) : (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5">
                  <span className="text-[13px] text-on-surface">
                    Squash and merge #{number} as you?{outcome === "partial" ? " It is a partial result." : ""}
                  </span>
                  <Button size="sm" onClick={doMerge} loading={merging} data-testid="merge-confirm">
                    Confirm merge
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>
                    Cancel
                  </Button>
                </div>
              )}
              <Button variant="ghost" icon="send" onClick={() => setShowChanges((v) => !v)} aria-expanded={showChanges} data-testid="changes-toggle">
                Ask for changes
              </Button>
            </div>
            {info && !info.mergeAllowed && (
              <p id="merge-reason" className="text-[12.5px] text-on-surface-variant" data-testid="merge-reason">
                Merge is disabled: {info.reason || "this pull request cannot be merged right now."}
              </p>
            )}
            {mergeErr && <ErrorNote>{mergeErr}</ErrorNote>}
          </>
        )}

        {showChanges && !merged && (
          <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-container-low p-4">
            <label htmlFor="followup" className="text-[13px] font-medium text-white">
              What should change?
            </label>
            <Textarea
              id="followup"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="e.g. Also handle an empty list, and add a test for it."
              maxLength={2000}
              className="min-h-[88px]"
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={sendChanges} loading={sending} disabled={!message.trim()} icon="send" data-testid="changes-send">
                Send to PatchLoop
              </Button>
              <span className="text-[12.5px] text-on-surface-variant">One new commit is pushed to the same branch. No new pull request.</span>
            </div>
            {sendErr && <ErrorNote>{sendErr}</ErrorNote>}
          </div>
        )}
      </div>
    </Card>
  );
}
