"use client";

import { useCallback, useEffect, useState } from "react";
import { errorMessage, tokensApi, type ApiToken } from "../../../_lib/api";
import { RequireAuth } from "../../../_lib/auth";
import { CopyButton } from "../../../_components/run/Actions";

function fmtDate(s: string | null) {
  return s ? new Date(s).toLocaleString() : "never";
}

function TokensInner() {
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);

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
    if (!window.confirm(`Revoke "${t.name}"? Anything using it stops working.`)) return;
    setRevoking(t.id);
    try {
      await tokensApi.revoke(t.id);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRevoking(null);
    }
  };

  const loginLine = created ? `patchloop login --token ${created}` : "";

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <div>
        <h1 className="text-2xl sm:text-3xl text-white font-semibold tracking-tight">API tokens</h1>
        <p className="mt-1 text-[13.5px] text-on-surface-variant">
          Tokens let the <code className="font-mono text-primary">patchloop</code> CLI and scripts call the API as you
          (sent as <code className="font-mono text-on-surface">Authorization: Bearer plk_…</code>). A token is shown once.
        </p>
      </div>

      <form onSubmit={create} className="rounded-xl border border-outline-variant/60 bg-[#0b0e15] p-4 sm:p-5 flex flex-col sm:flex-row gap-3 sm:items-end">
        <label className="flex-1 flex flex-col gap-1.5">
          <span className="text-[11px] font-mono text-on-surface-variant">Token name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. laptop CLI"
            maxLength={64}
            data-testid="token-name"
            className="w-full px-3.5 py-2.5 bg-surface-container-low border border-white/10 rounded-lg text-sm text-on-surface placeholder-on-surface-variant/60 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary"
          />
        </label>
        <button
          type="submit"
          disabled={busy || !name.trim()}
          className="inline-flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg bg-primary text-black text-[13px] font-semibold hover:bg-[#34d399] disabled:opacity-60"
        >
          <span className="material-symbols-outlined text-[17px]">key</span>
          {busy ? "Creating…" : "Create token"}
        </button>
      </form>

      {error && <p className="text-[13px] text-error">{error}</p>}

      {created && (
        <section data-testid="new-token" className="rounded-xl border border-primary/50 bg-primary/5 p-4 sm:p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2 text-primary text-[14px] font-medium">
            <span className="material-symbols-outlined text-[18px]">warning</span>
            Copy this token now. You will not see it again.
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <code className="flex-1 min-w-0 break-all font-mono text-[13px] text-white bg-[#07090e] border border-outline-variant/60 rounded-lg px-3 py-2.5">
              {created}
            </code>
            <CopyButton text={created} label="Copy token" />
          </div>
          <div className="text-[12px] font-mono text-on-surface-variant">Sign the CLI in with:</div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <code className="flex-1 min-w-0 break-all font-mono text-[13px] text-secondary bg-[#07090e] border border-outline-variant/60 rounded-lg px-3 py-2.5">
              <span className="text-primary select-none">$ </span>
              {loginLine}
            </code>
            <CopyButton text={loginLine} label="Copy command" />
          </div>
          <button onClick={() => setCreated(null)} className="self-start text-[12px] text-on-surface-variant hover:text-white underline">
            I saved it, hide the token
          </button>
        </section>
      )}

      <section className="rounded-xl border border-outline-variant/60 bg-[#0b0e15] overflow-hidden">
        <div className="px-4 sm:px-5 py-3 border-b border-outline-variant/50">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-on-surface-variant">Active tokens</h2>
        </div>
        {!tokens ? (
          <div className="p-5 flex flex-col gap-2">
            {[0, 1].map((i) => (
              <div key={i} className="h-10 rounded bg-surface-container-low animate-pulse" />
            ))}
          </div>
        ) : tokens.length === 0 ? (
          <p className="px-5 py-8 text-center text-[13px] text-on-surface-variant">No tokens yet.</p>
        ) : (
          <ul className="divide-y divide-outline-variant/30">
            {tokens.map((t) => (
              <li key={t.id} className="px-4 sm:px-5 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[13.5px] text-white">{t.name}</div>
                  <div className="font-mono text-[11px] text-on-surface-variant">
                    {t.prefix}… · created {fmtDate(t.createdAt)} · last used {fmtDate(t.lastUsedAt)}
                  </div>
                </div>
                <button
                  onClick={() => revoke(t)}
                  disabled={revoking === t.id}
                  className="self-start sm:self-auto inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-error/40 text-error text-[12.5px] hover:bg-error/10 disabled:opacity-60"
                >
                  <span className="material-symbols-outlined text-[15px]">delete</span>
                  {revoking === t.id ? "Revoking…" : "Revoke"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
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
