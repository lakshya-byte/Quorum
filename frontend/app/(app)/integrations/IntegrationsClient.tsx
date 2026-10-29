"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, errorMessage, githubApi, slackApi, type GithubStatus, type SlackLinkCode, type SlackStatus } from "../../_lib/api";
import { RequireAuth } from "../../_lib/auth";
import { CopyButton } from "../../_components/run/Actions";
import { Badge, Button, Card, CardBody, CardHeader, ErrorNote, Field, Icon, Input, PageHeader, Skeleton, useToast } from "../../_ui";

function GithubCard() {
  const { toast } = useToast();
  const [st, setSt] = useState<GithubStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<"install" | "demo" | "off" | null>(null);

  const load = useCallback(async () => {
    try {
      setSt(await githubApi.status());
    } catch (e) {
      setErr(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    load();
    const r = new URLSearchParams(window.location.search).get("github");
    if (r === "connected") toast("GitHub connected. Pick a repository to start.", "success");
    if (r === "error") toast("GitHub connection failed. Try installing the app again.", "error");
  }, [load, toast]);

  const install = async () => {
    setBusy("install");
    setErr(null);
    try {
      const { url } = await githubApi.connectUrl();
      window.location.href = url;
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 503 ? "The GitHub App is not configured on this server yet (no app credentials). You can still use the demo account below." : errorMessage(e));
      setBusy(null);
    }
  };
  const demo = async () => {
    setBusy("demo");
    setErr(null);
    try {
      await githubApi.demo();
      await load();
      toast("Demo account connected. Three bundled repositories are available.", "success");
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  const disconnect = async () => {
    setBusy("off");
    try {
      await githubApi.disconnect();
      await load();
      toast("GitHub disconnected.", "info");
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card data-testid="github-card">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Icon name="github" size={18} /> GitHub
          </span>
        }
        description="PatchLoop reads the repositories you grant and opens pull requests on patchloop/ branches. It never pushes to your default branch."
        action={st ? <Badge tone={st.connected ? "success" : "neutral"} icon={st.connected ? "check" : undefined}>{st.connected ? "Connected" : "Not connected"}</Badge> : undefined}
      />
      <CardBody className="flex flex-col gap-4">
        {!st && !err && <Skeleton className="h-20" />}
        {err && <ErrorNote tone={st ? "error" : "warning"}>{err}</ErrorNote>}
        {st && !st.connected && (
          <>
            <div className="rounded-lg border border-border bg-surface-container-low p-4">
              <h3 className="text-[14px] font-semibold text-white">Install the GitHub App</h3>
              <p className="mt-1 text-[13px] leading-5 text-on-surface-variant">
                You choose which repositories to grant. Permissions: contents and pull requests (read/write), issues (read/write), checks and metadata (read). Merging uses your own GitHub permission.
              </p>
              <Button className="mt-3" icon="github" onClick={install} loading={busy === "install"} data-testid="gh-install">
                Install GitHub App
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border-strong p-4">
              <div className="min-w-0 flex-1">
                <h3 className="text-[14px] font-semibold text-white">Or try with a demo account</h3>
                <p className="text-[13px] text-on-surface-variant">Works offline: three bundled demo repositories, fake pull requests, no GitHub access.</p>
              </div>
              <Button variant="secondary" onClick={demo} loading={busy === "demo"} data-testid="gh-demo">
                Use demo account
              </Button>
            </div>
          </>
        )}
        {st?.connected && (
          <>
            <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3">
              <div>
                <dt className="text-[12px] text-on-surface-variant">Account</dt>
                <dd className="font-mono text-[13.5px] text-white">{st.login || "unknown"}</dd>
              </div>
              <div>
                <dt className="text-[12px] text-on-surface-variant">Mode</dt>
                <dd className="text-[13.5px] text-white">{st.mode === "demo" ? "Demo (offline)" : "GitHub App"}</dd>
              </div>
              <div>
                <dt className="text-[12px] text-on-surface-variant">Repositories granted</dt>
                <dd className="text-[13.5px] text-white" data-testid="repo-count">{st.repoCount ?? "–"}</dd>
              </div>
            </dl>
            <div className="flex flex-wrap gap-2">
              {st.mode === "app" && (
                <a
                  href={st.installationId ? `https://github.com/settings/installations/${st.installationId}` : "https://github.com/settings/installations"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-surface-container-high px-3 text-[13px] font-semibold text-on-surface hover:bg-surface-bright"
                >
                  Manage repositories on GitHub <Icon name="external" size={13} />
                </a>
              )}
              <Button size="sm" variant="danger" onClick={disconnect} loading={busy === "off"}>
                Disconnect
              </Button>
            </div>
            {st.mode === "demo" && <ErrorNote tone="info">Demo mode: pull requests and merges are simulated and nothing touches GitHub.</ErrorNote>}
          </>
        )}
      </CardBody>
    </Card>
  );
}

const SLACK_EXAMPLES = [
  { label: "Link your account", text: "/patchloop link {CODE}" },
  { label: "Start a fix", text: "/patchloop fix reserve() rejects the last unit repo:demo/inventory-api" },
  { label: "Paste an alert", text: "@PatchLoop <paste the error or alert text>" },
];

function SlackCard() {
  const { toast } = useToast();
  const [st, setSt] = useState<SlackStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [hook, setHook] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [hookErr, setHookErr] = useState<string | null>(null);
  const [code, setCode] = useState<SlackLinkCode | null>(null);
  const [coding, setCoding] = useState(false);

  useEffect(() => {
    slackApi
      .get()
      .then(setSt)
      .catch((e) => setErr(errorMessage(e)));
  }, []);

  const save = async () => {
    setSaving(true);
    setHookErr(null);
    try {
      setSt(await slackApi.save(hook.trim()));
      setHook("");
      toast("Slack webhook saved.", "success");
    } catch (e) {
      setHookErr(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };
  const test = async () => {
    setTesting(true);
    try {
      await slackApi.test();
      toast("Test message sent to Slack.", "success");
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setTesting(false);
    }
  };
  const clear = async () => {
    try {
      await slackApi.clear();
      setSt({ configured: false });
      toast("Slack webhook removed.", "info");
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };
  const genCode = async () => {
    setCoding(true);
    try {
      setCode(await slackApi.linkCode());
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setCoding(false);
    }
  };

  return (
    <Card data-testid="slack-card">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Icon name="slack" size={18} /> Slack
          </span>
        }
        description="Get a message when a run finishes. Optionally start fixes and merge from Slack."
        action={st ? <Badge tone={st.configured ? "success" : "neutral"}>{st.configured ? "Webhook set" : "No webhook"}</Badge> : undefined}
      />
      <CardBody className="flex flex-col gap-6">
        {err && <ErrorNote>{err}</ErrorNote>}

        <section className="flex flex-col gap-3">
          <h3 className="text-[14px] font-semibold text-white">Completion messages (incoming webhook)</h3>
          {st?.configured && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-container-low px-3 py-2">
              <Icon name="check-circle" size={16} className="text-primary" />
              <span className="font-mono text-[12.5px] text-on-surface" data-testid="slack-masked">{st.webhookUrlMasked}</span>
              <span className="ml-auto flex gap-2">
                <Button size="sm" variant="secondary" onClick={test} loading={testing} data-testid="slack-test">
                  Send test message
                </Button>
                <Button size="sm" variant="ghost" onClick={clear}>
                  Remove
                </Button>
              </span>
            </div>
          )}
          <Field label={st?.configured ? "Replace webhook URL" : "Webhook URL"} hint="Create an incoming webhook in your Slack workspace. It must start with https://hooks.slack.com/." error={hookErr}>
            {(p) => (
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input {...p} value={hook} onChange={(e) => setHook(e.target.value)} placeholder="https://hooks.slack.com/services/…" autoComplete="off" spellCheck={false} data-testid="slack-input" />
                <Button onClick={save} loading={saving} disabled={!hook.trim()} data-testid="slack-save">
                  Save
                </Button>
              </div>
            )}
          </Field>
        </section>

        <section className="flex flex-col gap-3 border-t border-border pt-5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[14px] font-semibold text-white">Work from Slack (slash command and buttons)</h3>
            <Badge tone="warning">needs Slack app setup</Badge>
          </div>
          <p className="text-[13px] leading-5 text-on-surface-variant">
            This needs the PatchLoop Slack app installed in your workspace by whoever runs this server. See the setup docs. Once it is installed, link your Slack user with a one-time code.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" icon="key" onClick={genCode} loading={coding} data-testid="slack-code-btn">
              Generate link code
            </Button>
            {code && (
              <span className="flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/5 px-3 py-1.5">
                <span className="font-mono text-[16px] font-semibold tracking-widest text-primary" data-testid="slack-code">{code.code}</span>
                <span className="text-[12px] text-on-surface-variant">expires {new Date(code.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
              </span>
            )}
          </div>
          <ul className="flex flex-col gap-2">
            {SLACK_EXAMPLES.map((x) => {
              const text = x.text.replace("{CODE}", code?.code ?? "CODE");
              return (
                <li key={x.label} className="flex flex-col gap-1.5 rounded-lg border border-border bg-bg px-3 py-2 sm:flex-row sm:items-center sm:gap-2">
                  <span className="shrink-0 text-[12px] text-on-surface-variant sm:w-28">{x.label}</span>
                  <code className="min-w-0 flex-1 break-words font-mono text-[12.5px] text-on-surface">{text}</code>
                  <span className="self-start sm:self-auto"><CopyButton text={text} label="Copy" variant="ghost" /></span>
                </li>
              );
            })}
          </ul>
        </section>
      </CardBody>
    </Card>
  );
}

function TriggersCard() {
  return (
    <Card>
      <CardHeader
        title="Start from GitHub or the CLI"
        description="More ways to start the same fix."
        action={<Badge tone="warning">GitHub triggers need app setup</Badge>}
      />
      <CardBody className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-bg p-4">
          <h3 className="flex items-center gap-2 text-[13.5px] font-semibold text-white"><Icon name="github" size={15} /> On an issue</h3>
          <p className="mt-1.5 text-[13px] leading-5 text-on-surface-variant">
            Add the label <code className="rounded bg-surface-container-high px-1 font-mono text-[12px] text-white">patchloop</code> or comment <code className="rounded bg-surface-container-high px-1 font-mono text-[12px] text-white">@patchloop fix</code>. Requires the GitHub App with webhooks enabled.
          </p>
        </div>
        <div className="rounded-lg border border-border bg-bg p-4">
          <h3 className="flex items-center gap-2 text-[13.5px] font-semibold text-white"><Icon name="terminal" size={15} /> From the terminal</h3>
          <p className="mt-1.5 text-[13px] leading-5 text-on-surface-variant">
            <code className="rounded bg-surface-container-high px-1 font-mono text-[12px] text-white">patchloop fix --repo owner/name &quot;problem&quot;</code> with an API token from{" "}
            <a href="/settings/tokens" className="text-primary underline">API tokens</a>.
          </p>
        </div>
      </CardBody>
    </Card>
  );
}

export default function IntegrationsClient() {
  return (
    <RequireAuth>
      <div className="flex flex-col gap-6">
        <PageHeader title="Integrations" description="Connect where your code lives and where your team talks." />
        <GithubCard />
        <SlackCard />
        <TriggersCard />
      </div>
    </RequireAuth>
  );
}
