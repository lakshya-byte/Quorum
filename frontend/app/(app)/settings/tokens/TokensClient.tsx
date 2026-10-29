"use client";

import { useCallback, useEffect, useState } from "react";
import { errorMessage, tokensApi, type ApiToken } from "../../../_lib/api";
import { RequireAuth } from "../../../_lib/auth";
import { CopyButton } from "../../../_components/run/Actions";
import { Button, Card, EmptyState, ErrorNote, Field, Icon, Input, PageHeader, Skeleton, useToast } from "../../../_ui";

function fmtDate(s: string | null) {
  return s ? new Date(s).toLocaleString() : "never";
}

function TokensInner() {
  const { toast } = useToast();
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTokens((await tokensApi.list()) || []);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    load();
  }, [load]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { token } = await tokensApi.create(name.trim());
      setCreated(token);
      setName("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (t: ApiToken) => {
    setRevoking(t.id);
    try {
      await tokensApi.revoke(t.id);
      toast(`Revoked "${t.name}".`, "info");
      setConfirming(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRevoking(null);
    }
  };

  const loginLine = created ? `patchloop login --token ${created}` : "";

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageHeader
        title="API tokens"
        description={
          <>
            Tokens let the <code className="font-mono text-primary">patchloop</code> CLI and scripts call the API as you, sent as{" "}
            <code className="font-mono text-on-surface">Authorization: Bearer plk_…</code>. A token is shown once.
          </>
        }
      />

      <Card className="p-5">
        <form onSubmit={create} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <Field label="Token name" className="flex-1">
            {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. laptop CLI" maxLength={64} data-testid="token-name" />}
          </Field>
          <Button type="submit" icon="key" loading={busy} disabled={!name.trim()} data-testid="token-create">
            Create token
          </Button>
        </form>
      </Card>

      {error && <ErrorNote>{error}</ErrorNote>}

      {created && (
        <section data-testid="new-token" className="flex flex-col gap-3 rounded-xl border border-primary/45 bg-primary/5 p-5">
          <div className="flex items-center gap-2 text-[14px] font-semibold text-primary">
            <Icon name="alert" size={16} />
            Copy this token now. You will not see it again.
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <code className="min-w-0 flex-1 break-all rounded-lg border border-border bg-bg px-3 py-2.5 font-mono text-[13px] text-white">{created}</code>
            <CopyButton text={created} label="Copy token" />
          </div>
          <div className="text-[12.5px] text-on-surface-variant">Sign the CLI in with:</div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <code className="min-w-0 flex-1 break-all rounded-lg border border-border bg-bg px-3 py-2.5 font-mono text-[13px] text-secondary">
              <span className="select-none text-primary">$ </span>
              {loginLine}
            </code>
            <CopyButton text={loginLine} label="Copy command" />
          </div>
          <button onClick={() => setCreated(null)} className="focus-ring self-start rounded text-[13px] text-on-surface-variant underline hover:text-white">
            I saved it, hide the token
          </button>
        </section>
      )}

      <Card className="overflow-hidden">
        <div className="border-b border-border px-5 py-3.5">
          <h2 className="text-[15px] font-semibold text-white">Active tokens</h2>
        </div>
        {!tokens ? (
          <div className="flex flex-col gap-2 p-5">
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
          </div>
        ) : tokens.length === 0 ? (
          <EmptyState icon="key" title="No tokens yet" description="Create one above to sign the CLI in." />
        ) : (
          <ul className="divide-y divide-border">
            {tokens.map((t) => (
              <li key={t.id} className="flex flex-col justify-between gap-2 px-5 py-3.5 sm:flex-row sm:items-center">
                <div className="min-w-0">
                  <div className="text-[14px] font-medium text-white">{t.name}</div>
                  <div className="font-mono text-[11.5px] text-on-surface-variant">
                    {t.prefix}… · created {fmtDate(t.createdAt)} · last used {fmtDate(t.lastUsedAt)}
                  </div>
                </div>
                {confirming === t.id ? (
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] text-on-surface-variant">Anything using it stops working.</span>
                    <Button size="sm" variant="danger" loading={revoking === t.id} onClick={() => revoke(t)}>
                      Revoke
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button size="sm" variant="secondary" icon="trash" onClick={() => setConfirming(t.id)} aria-label={`Revoke ${t.name}`}>
                    Revoke
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export default function TokensClient() {
  return (
    <RequireAuth>
      <TokensInner />
    </RequireAuth>
  );
}
