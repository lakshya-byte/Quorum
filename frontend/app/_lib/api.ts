// Thin client for the PatchLoop backend. Cookies carry the session, so every
// call uses credentials: "include". A 401 triggers one refresh attempt.

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
};

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
};

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

let refreshing: Promise<boolean> | null = null;

/** POST /api/auth/refresh once; concurrent callers share the same attempt. */
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

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}, retried = false): Promise<T> {
  const { json, headers, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...rest,
      credentials: "include",
      headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, `Cannot reach the PatchLoop API at ${API_URL}. Is the backend running?`);
  }
  if (res.status === 401 && !retried && !NO_REFRESH.includes(path)) {
    if (await refreshSession()) return api<T>(path, init, true);
  }
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

export const tokensApi = {
  list: () => api<ApiToken[] | null>("/api/tokens"),
  create: (name: string) => api<{ token: string }>("/api/tokens", { method: "POST", json: { name } }),
  revoke: (id: string) => api<unknown>(`/api/tokens/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
