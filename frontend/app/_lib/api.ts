// Thin client for the PatchLoop backend. Clerk owns the session; every call
// sends the current Clerk session token as "Authorization: Bearer ...".

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080").replace(/\/$/, "");

export type User = { id: string; email: string; companyName: string; emailVerified: boolean };
export type Bug = { id: string; title: string; issue: string; tier: string };
export type Engine = "graph" | "loop";

export type Usage = { prompt_tokens?: number; completion_tokens?: number; calls?: number };

export type RunNode = {
  id: number;
  parent: number | null;
  depth: number;
  idea?: string;
  strategy?: string | null;
  code?: string;
  output?: string;
  passed: number;
  total: number;
  score?: number;
  model?: string | null;
  latency_ms?: number;
  tokens?: number | { prompt_tokens?: number; completion_tokens?: number };
  policy?: { ok: boolean; reasons?: string[] };
  security?: { ok: boolean; new_findings?: unknown[] };
  /** multi-file candidate: path -> full file content (code is the primary file) */
  files?: Record<string, string>;
  /** unified diff text for the whole candidate (capped by the agent) */
  diff?: string;
};

/** What the agent reports in the completion callback (see agent/app/runs.py safety_summary). */
export type RunSafety = {
  guard?: { input?: string; output?: string } | string;
  policy?: { best_ok?: boolean; blocked?: number; candidates?: number; reasons?: string[] } | string;
  security?: { best_ok?: boolean; blocked?: number; scanned?: boolean; scanner?: string } | string;
};

/** Collapse RunSafety into three words for the history table: pass | fail | n/a. */
export function safetySummary(
  s: RunSafety | null | undefined,
): { guard: string; policy: string; security: string; allPass: boolean; anyFail: boolean } | null {
  if (!s) return null;
  // "n/a" means the check did not run (for example no output guard on an unsolved run); it is never shown as a pass.
  let guard = "n/a";
  if (typeof s.guard === "string") guard = s.guard;
  else if (s.guard) {
    const v = Object.values(s.guard);
    guard = v.some((x) => x === "fail" || x === "block" || x === "blocked") ? "fail" : v.length > 0 && v.every((x) => x === "pass") ? "pass" : "n/a";
  }
  const best = (o: { best_ok?: boolean | null }) => (o.best_ok === false ? "fail" : o.best_ok === true ? "pass" : "n/a");
  const policy = typeof s.policy === "string" ? s.policy : s.policy ? best(s.policy) : "n/a";
  const security = typeof s.security === "string" ? s.security : s.security ? best(s.security) : "n/a";
  const all = [guard, policy, security];
  return { guard, policy, security, allPass: all.every((v) => v === "pass"), anyFail: all.some((v) => v === "fail") };
}

export type Run = {
  id: string;
  userId: string;
  bugId: string;
  agentRunId?: string;
  mode: string;
  engine: string;
  status: string;
  solved: boolean;
  bestNodeId: number | null;
  nodes: RunNode[] | null;
  usage: Usage | null;
  latencyMs: number | null;
  prUrl: string | null;
  createdAt: string;
  completedAt: string | null;
  kind?: "bug" | "repo";
  repo?: string;
  branch?: string;
  task?: string;
  prNumber?: number | null;
  filesChanged?: number | null;
  source?: "web" | "cli" | "slack" | "github";
  parentRunId?: string | null;
  prBranch?: string | null;
  merged?: { by?: string; at?: string } | null;
  cost?: { tokens?: number; usd?: number | null } | null;
  safety?: RunSafety | null;
  /** true once the completion message went to Slack (set by the backend, shortly after the run finishes) */
  slackSent?: boolean;
  /** tests passed by the best candidate (present even where the list omits nodes) */
  bestPassed?: number;
  bestTotal?: number;
  traceId?: string | null;
  langsmithUrl?: string | null;
};

export type GithubStatus = {
  connected: boolean;
  mode: "app" | "demo" | null;
  login?: string | null;
  avatarUrl?: string | null;
  installationId?: number | string | null;
  appConfigured?: boolean;
  repoCount?: number;
};
export type PrInfo = {
  url: string;
  number: number;
  state: string;
  mergeable: boolean | null;
  checks: { state: "success" | "failure" | "pending" | "none"; failing?: string[] };
  mergeAllowed: boolean;
  reason?: string;
  merged?: { by?: string; at?: string } | null;
};
export type MergeResult = { merged?: boolean; message?: string; warning?: string; url?: string };
export type SlackLinkCode = { code: string; expiresAt: string };
export type Notification = { id: string; kind: string; title: string; body?: string; runId?: string; read: boolean; createdAt: string };
export type RepoSummary = {
  fullName: string;
  private: boolean;
  defaultBranch: string;
  description: string;
  language: string;
  updatedAt: string;
};
export type BranchInfo = { name: string; default: boolean };
export type SlackStatus = { configured: boolean; webhookUrlMasked?: string | null };

export type CreateRunResponse = { runId: string; mode: string; engine: string; notice?: string };
export type ApiToken = { id: string; name: string; prefix: string; createdAt: string; lastUsedAt: string | null };

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** Clerk session token for the API (null when signed out or Clerk has not loaded). */
export async function getAuthToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  try {
    return (await (window as unknown as { Clerk?: { session?: { getToken: () => Promise<string | null> } } }).Clerk?.session?.getToken()) ?? null;
  } catch {
    return null;
  }
}

/* Cookie-session refresh, replaced by Clerk (it refreshes its own tokens):
let refreshing: Promise<boolean> | null = null;

// POST /api/auth/refresh once; concurrent callers share the same attempt.
export function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(`${API_URL}/api/auth/refresh`, { method: "POST", credentials: "include" })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        setTimeout(() => (refreshing = null), 0);
      });
  }
  return refreshing;
}

const NO_REFRESH = ["/api/auth/login", "/api/auth/signup", "/api/auth/verify-otp", "/api/auth/resend-otp", "/api/auth/refresh", "/api/auth/logout"];
*/

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const token = await getAuthToken();
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...rest,
      headers: {
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, `Cannot reach the PatchLoop API at ${API_URL}. Is the backend running?`);
  }
  // if (res.status === 401 && !retried && !NO_REFRESH.includes(path)) {
  //   if (await refreshSession()) return api<T>(path, init, true);
  // }
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) {
    const b = (body || {}) as { error?: string; code?: string };
    throw new ApiError(res.status, b.error || `Request failed (${res.status})`, b.code);
  }
  return body as T;
}

export const errorMessage = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

// ----- auth -----
export const authApi = {
  signup: (email: string, password: string, companyName: string) =>
    api<{ message: string; user: User }>("/api/auth/signup", { method: "POST", json: { email, password, companyName } }),
  verifyOtp: (email: string, code: string) =>
    api<{ user: User }>("/api/auth/verify-otp", { method: "POST", json: { email, code } }),
  resendOtp: (email: string) => api<{ message: string }>("/api/auth/resend-otp", { method: "POST", json: { email } }),
  login: (email: string, password: string) =>
    api<{ user: User }>("/api/auth/login", { method: "POST", json: { email, password } }),
  logout: () => api<{ message: string }>("/api/auth/logout", { method: "POST" }),
  me: () => api<{ user: User }>("/api/auth/me"),
};

// ----- runs, bugs, tokens -----
export const runsApi = {
  bugs: () => api<Bug[]>("/api/bugs"),
  create: (bugId: string, engine: Engine, replay: boolean) =>
    api<CreateRunResponse>("/api/runs", { method: "POST", json: { bugId, engine, replay } }),
  list: () => api<Run[] | null>("/api/runs"),
  get: (id: string) => api<Run>(`/api/runs/${encodeURIComponent(id)}`),
  openPr: (id: string) => api<{ url: string }>(`/api/runs/${encodeURIComponent(id)}/pr`, { method: "POST" }),
  eventsUrl: (id: string) => `${API_URL}/api/runs/${encodeURIComponent(id)}/events`,
};

export const demoApi = {
  bugs: () => api<Bug[]>("/api/demo/bugs"),
  create: (bugId: string) => api<CreateRunResponse>("/api/demo/runs", { method: "POST", json: { bugId } }),
  eventsUrl: (id: string) => `${API_URL}/api/demo/runs/${encodeURIComponent(id)}/events`,
};

export const githubApi = {
  status: () => api<GithubStatus>("/api/github/status"),
  connectUrl: () => api<{ url: string }>("/api/github/connect"),
  demo: () => api<GithubStatus>("/api/github/demo", { method: "POST" }),
  disconnect: () => api<unknown>("/api/github", { method: "DELETE" }),
  repos: (q = "") => api<RepoSummary[] | null>(`/api/github/repos?q=${encodeURIComponent(q)}`),
  branches: (fullName: string) => {
    const [owner, repo] = fullName.split("/");
    return api<BranchInfo[] | null>(`/api/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/branches`);
  },
};

export const slackApi = {
  get: () => api<SlackStatus>("/api/settings/slack"),
  save: (webhookUrl: string) => api<SlackStatus>("/api/settings/slack", { method: "PUT", json: { webhookUrl } }),
  clear: () => api<unknown>("/api/settings/slack", { method: "DELETE" }),
  test: () => api<{ message?: string }>("/api/settings/slack/test", { method: "POST" }),
  linkCode: () => api<SlackLinkCode>("/api/slack/link-code", { method: "POST" }),
};

export const tasksApi = {
  create: (repo: string, branch: string, task: string, autoPr = true) =>
    api<{ runId: string }>("/api/tasks", { method: "POST", json: { repo, branch, task, autoPr } }),
};

export const prApi = {
  get: (id: string) => api<PrInfo>(`/api/runs/${encodeURIComponent(id)}/pr`),
  merge: (id: string, method: "squash" | "merge" | "rebase" = "squash") =>
    api<MergeResult>(`/api/runs/${encodeURIComponent(id)}/merge`, { method: "POST", json: { method } }),
  followup: (id: string, message: string) =>
    api<{ runId: string }>(`/api/runs/${encodeURIComponent(id)}/followup`, { method: "POST", json: { message } }),
};

export const notificationsApi = {
  // The backend answers {notifications, unread}; a bare array (older mock) is accepted too.
  list: async (): Promise<{ notifications: Notification[]; unread: number }> => {
    const r = await api<{ notifications?: Notification[] | null; unread?: number } | Notification[] | null>("/api/notifications");
    if (Array.isArray(r)) return { notifications: r, unread: r.filter((n) => !n.read).length };
    const notifications = r?.notifications || [];
    return { notifications, unread: r?.unread ?? notifications.filter((n) => !n.read).length };
  },
  read: (id: string) => api<unknown>(`/api/notifications/${encodeURIComponent(id)}/read`, { method: "POST" }),
};

export const tokensApi = {
  list: () => api<ApiToken[] | null>("/api/tokens"),
  create: (name: string) => api<{ token: string }>("/api/tokens", { method: "POST", json: { name } }),
  revoke: (id: string) => api<unknown>(`/api/tokens/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
