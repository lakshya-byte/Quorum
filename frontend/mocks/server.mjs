#!/usr/bin/env node
// PatchLoop mock backend. Dependency-free (node:http only).
// Implements the public backend API (auth, bugs, runs, SSE events, PRs, tokens,
// guest demo) with in-memory state, so the frontend can be built and tested
// without Go, Mongo or the Python agent.
//
//   MOCK_PORT        port to listen on (default 8080)
//   FRONTEND_ORIGIN  allowed CORS origin(s), comma separated (default http://localhost:3000)
//   MOCK_SPEED       timing multiplier for scripted runs (default 1; 2 = twice as slow)
//   MOCK_DEMO_LIMIT  guest runs per hour per IP (default 3)
//   MOCK_ACCESS_TTL  access-cookie lifetime in seconds (default 900)
//   MOCK_DROP_ONCE   "1" = cut each run's first stream after the 4th event (tests reconnect)
//
// Any OTP code "123456" verifies. Emails are never logged.

import http from "node:http";
import crypto from "node:crypto";
import { BUGS, getBug, publicBug } from "./bugs.mjs";

const PORT = Number(process.env.MOCK_PORT || 8080);
const ORIGINS = (process.env.FRONTEND_ORIGIN || "http://localhost:3000")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const SPEED = Number(process.env.MOCK_SPEED || 1);
const DEMO_LIMIT = Number(process.env.MOCK_DEMO_LIMIT || 3);
const ACCESS_TTL = Number(process.env.MOCK_ACCESS_TTL || 900);
const REFRESH_TTL = 7 * 24 * 3600;
const DROP_ONCE = process.env.MOCK_DROP_ONCE === "1";

const ACCESS_COOKIE = "patchloop_access_token";
const REFRESH_COOKIE = "patchloop_refresh_token";

// ---------- state ----------
const users = new Map(); // email -> user
const usersById = new Map();
const accessTokens = new Map(); // token -> { userId, exp }
const refreshTokens = new Map(); // token -> { userId, exp }
const apiTokens = new Map(); // id -> { id, userId, name, prefix, hash, createdAt, lastUsedAt }
const runs = new Map(); // id -> run
const demoHits = new Map(); // ip -> [timestamps]
let prCounter = 41;

const rid = (n = 12) => crypto.randomBytes(n).toString("hex");
const sha = (s) => crypto.createHash("sha256").update(s).digest("hex");
const now = () => new Date().toISOString();

// ---------- http helpers ----------
function cors(req, res) {
  const origin = req.headers.origin;
  if (origin && ORIGINS.includes(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Access-Control-Allow-Credentials", "true");
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, Last-Event-ID");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
}

function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}
const err = (res, status, message) => json(res, status, { error: message });

function readBody(req) {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (c) => {
      data += c;
      if (data.length > 1e6) req.destroy();
    });
    req.on("end", () => {
      if (!data) return resolve({});
      try {
        resolve(JSON.parse(data));
      } catch {
        resolve(null);
      }
    });
  });
}

function parseCookies(req) {
  const out = {};
  for (const part of (req.headers.cookie || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}

function cookie(name, value, maxAge) {
  return `${name}=${value}; Path=/; Max-Age=${maxAge}; HttpOnly; SameSite=Lax`;
}

function issueSession(res, userId) {
  const access = rid(24);
  const refresh = rid(32);
  accessTokens.set(access, { userId, exp: Date.now() + ACCESS_TTL * 1000 });
  refreshTokens.set(refresh, { userId, exp: Date.now() + REFRESH_TTL * 1000 });
  res.setHeader("Set-Cookie", [cookie(ACCESS_COOKIE, access, ACCESS_TTL), cookie(REFRESH_COOKIE, refresh, REFRESH_TTL)]);
}

function clearSession(res) {
  res.setHeader("Set-Cookie", [cookie(ACCESS_COOKIE, "", -1), cookie(REFRESH_COOKIE, "", -1)]);
}

/** Resolve the caller: access cookie OR "Authorization: Bearer plk_...". */
function authUser(req) {
  const h = req.headers.authorization || "";
  if (h.startsWith("Bearer ")) {
    const raw = h.slice(7).trim();
    if (!raw.startsWith("plk_")) return null;
    const hash = sha(raw);
    for (const t of apiTokens.values()) {
      if (t.hash === hash) {
        t.lastUsedAt = now();
        return usersById.get(t.userId) || null;
      }
    }
    return null;
  }
  const tok = parseCookies(req)[ACCESS_COOKIE];
  const s = tok && accessTokens.get(tok);
  if (!s || s.exp < Date.now()) return null;
  return usersById.get(s.userId) || null;
}

const userResponse = (u) => ({ id: u.id, email: u.email, companyName: u.companyName, emailVerified: u.verified });
const emailOk = (e) => typeof e === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);

// ---------- scripted runs ----------
function testOutput(bug, failing) {
  const total = bug.tests;
  const dots = Array.from({ length: total }, (_, i) => (i < failing.length ? "F" : ".")).join("");
  const fails = failing
    .map(
      (t) =>
        `======================================================================\nFAIL: ${t} (test_${bug.id}.Test)\n----------------------------------------------------------------------\nTraceback (most recent call last):\n  File "test_${bug.id}.py", line 12, in ${t}\nAssertionError: expected value did not match\n`
    )
    .join("\n");
  const tail = `----------------------------------------------------------------------\nRan ${total} tests in 0.00${2 + failing.length}s\n\n${failing.length ? `FAILED (failures=${failing.length})` : "OK"}`;
  return `${dots}\n${fails}${fails ? "\n" : ""}${tail}`;
}

function changedLines(a, b) {
  const A = a.split("\n");
  const B = b.split("\n");
  const setA = new Set(A);
  const setB = new Set(B);
  return B.filter((l) => !setA.has(l)).length + A.filter((l) => !setB.has(l)).length;
}

function score(passed, total, code, buggy) {
  if (!total) return 0;
  return Math.round((passed / total - 0.001 * Math.min(changedLines(buggy, code), 50)) * 1000) / 1000;
}

/** Build the event script [{at, type, data}] for a run. */
function buildScript(bug, engine, mode) {
  const s = mode === "replay" ? 0.6 * SPEED : SPEED;
  const ev = [];
  let t = 0;
  const push = (gap, type, data) => {
    t += Math.round(gap * s);
    ev.push({ at: t, type, data });
  };
  const graph = engine !== "loop";
  const nano = "nemotron-nano (Nebius Token Factory)";
  const sup = "nemotron-super (Nebius Token Factory)";
  let tokens = 0;

  const node = (id, parent, depth, variant, extra = {}) => {
    const code = bug[variant];
    const failing = extra.failing ?? bug.failing?.[variant] ?? [];
    const blocked = extra.policy && !extra.policy.ok;
    const total = bug.tests;
    const passed = blocked ? 0 : total - failing.length;
    const nodeTokens = id === 0 ? 0 : 900 + ((id * 137) % 600);
    tokens += nodeTokens;
    const base = {
      id,
      parent,
      depth,
      idea: extra.idea,
      code,
      output: blocked
        ? `Blocked by the policy gate before execution.\n${extra.policy.reasons.map((r) => `- ${r}`).join("\n")}`
        : testOutput(bug, failing),
      passed,
      total,
      score: blocked ? 0 : score(passed, total, code, bug.buggy),
      model: id === 0 ? null : depth > 1 ? sup : nano,
    };
    if (!graph) return base;
    return {
      ...base,
      strategy: extra.strategy ?? null,
      latency_ms: id === 0 ? 410 : 1800 + ((id * 311) % 2400),
      tokens: nodeTokens,
      policy: extra.policy ?? { ok: true, reasons: [] },
      security: extra.security ?? { ok: true, new_findings: [] },
    };
  };

  push(0, "run_started", { run_id: null, bug_id: bug.id, mode, engine });

  if (bug.kind === "blocked") {
    push(140, "guard", {
      stage: "input",
      verdict: "block",
      reasons: ["Prompt injection: asks to ignore previous instructions", "Requests pushing to main, which agents may never do"],
      latency_ms: 118,
    });
    push(120, "error", { stage: "guard", message: "The input guard blocked this issue. No agent was started and no sandbox was created." });
    push(30, "done", { solved: false, best: null, usage: { prompt_tokens: 0, completion_tokens: 0 }, latency_ms: 290, time_to_first_node_ms: null });
    push(10, "end", {});
    return ev;
  }

  if (graph) {
    push(110, "guard", { stage: "input", verdict: "pass", reasons: [], latency_ms: 96 });
    push(220, "triage", { cause: bug.cause, strategies: bug.strategies });
  }
  push(graph ? 120 : 250, "node", node(0, null, 0, "buggy", { idea: "Original code", failing: bug.failing.buggy }));
  push(120, "round", { depth: 1 });

  const S = bug.strategies;
  const r1 = [
    [1, "wrong", { idea: "Minimal one-line change to the core expression", strategy: S[0] }],
    [2, "partial", { idea: "Fix the core computation, keep the rest", strategy: S[1] }],
    [3, "policyBad", {
      idea: "Patch and publish the change directly",
      strategy: S[2],
      policy: { ok: false, reasons: ["Disallowed side effect: shell/network/env access in patch", "Agents may never push or touch credentials"] },
    }],
  ];
  const r1Gaps = [650, 380, 420];
  r1.forEach(([id, v, x], i) => push(r1Gaps[i], "node", node(id, 0, 1, v, x)));
  if (graph) {
    push(260, "critic", { node_id: 2, lesson: "The core logic is fixed; the remaining failures are the input-validation and edge-case tests. Keep this patch and add a guard clause." });
    push(160, "critic", { node_id: 1, lesson: "This patch changes the wrong expression and fails as many tests as the original. Drop this direction." });
  }

  if (bug.kind === "unsolved") {
    push(300, "round", { depth: 2 });
    push(900, "node", node(4, 2, 2, "securityBad", {
      idea: "Normalise the input dynamically before parsing",
      strategy: S[1],
      failing: ["test_week_date"],
      security: { ok: false, new_findings: [{ rule: "B307", severity: "MEDIUM", message: "Use of possibly insecure function - consider using safer ast.literal_eval.", line: 7 }] },
    }));
    push(500, "node", node(5, 2, 2, "correct", { idea: "Clamp leap seconds, keep fromisoformat", strategy: S[0], failing: ["test_week_date"] }));
    if (graph) push(240, "critic", { node_id: 5, lesson: "Week dates ('2024-W05-3') are not ISO calendar dates; fromisoformat cannot parse them. A different parser is needed." });
    push(300, "round", { depth: 3 });
    push(1000, "node", node(6, 5, 3, "correct", { idea: "Add a week-date branch via strptime %G-W%V-%u", strategy: S[2], failing: ["test_week_date"] }));
    push(450, "node", node(7, 5, 3, "partial", { idea: "Try fromisoformat first, fall back to strptime", strategy: S[0], failing: ["test_leap_second", "test_week_date"] }));
    if (graph) push(220, "critic", { node_id: 6, lesson: "Out of depth budget. Best candidate passes 6/7; a human should look at week-date support." });
    push(250, "done", {
      solved: false,
      best: 6,
      usage: { prompt_tokens: Math.round(tokens * 0.78), completion_tokens: Math.round(tokens * 0.22) },
      latency_ms: t + 250,
      time_to_first_node_ms: ev.find((e) => e.type === "node").at,
    });
    push(20, "end", {});
    return ev;
  }

  push(300, "round", { depth: 2 });
  push(1000, "node", node(4, 2, 2, "securityBad", {
    idea: "Coerce the argument before validating it",
    strategy: S[1],
    failing: [],
    security: graph
      ? { ok: false, new_findings: [{ rule: "B307", severity: "MEDIUM", message: "Use of possibly insecure function - consider using safer ast.literal_eval.", line: 3 }] }
      : undefined,
  }));
  push(480, "node", node(5, 2, 2, "correct", { idea: "Add the guard clause before computing", strategy: S[1], failing: [] }));
  if (graph) {
    push(200, "critic", { node_id: 5, lesson: "All tests pass with the smallest diff and a clean security scan. Prefer this over node 4, which passes but adds eval()." });
    push(180, "guard", { stage: "policy", verdict: "pass", reasons: ["1 candidate blocked earlier (node 3)", "Winner touches only the target file"], latency_ms: 4 });
    push(260, "guard", { stage: "output", verdict: "pass", reasons: [], latency_ms: 142 });
  }
  push(200, "done", {
    solved: true,
    best: 5,
    usage: { prompt_tokens: Math.round(tokens * 0.78), completion_tokens: Math.round(tokens * 0.22) },
    latency_ms: t + 200,
    time_to_first_node_ms: ev.find((e) => e.type === "node").at,
  });
  if (bug.autoPr && graph) push(600, "pr", { url: `https://github.com/patchloop-demo/demo-bugs/pull/${++prCounter}` });
  push(20, "end", {});
  return ev;
}

function createRun({ bug, engine, mode, userId, guest }) {
  const id = rid(12);
  const run = {
    id,
    userId: userId || null,
    bugId: bug.id,
    agentRunId: "ag_" + rid(6),
    mode,
    engine,
    status: "running",
    solved: false,
    bestNodeId: null,
    nodes: [],
    usage: { prompt_tokens: 0, completion_tokens: 0 },
    latencyMs: null,
    prUrl: null,
    createdAt: now(),
    completedAt: null,
    guest: !!guest,
    events: [], // emitted so far
    listeners: new Set(),
    finished: false,
    dropped: false,
  };
  runs.set(id, run);
  const script = buildScript(bug, engine, mode);
  for (const e of script) {
    setTimeout(() => {
      const data = e.type === "run_started" ? { ...e.data, run_id: id } : e.data;
      emit(run, e.type, data);
    }, e.at);
  }
  return run;
}

function emit(run, type, data) {
  if (run.finished) return;
  if (type === "node") run.nodes.push(data);
  if (type === "done") {
    run.solved = !!data.solved;
    run.bestNodeId = data.best ?? null;
    run.usage = data.usage;
    run.latencyMs = data.latency_ms ?? null;
    run.completedAt = now();
    run.status = run.events.some((e) => e.type === "error") ? "failed" : "completed";
  }
  if (type === "pr") run.prUrl = data.url;
  const msg = { type, data };
  run.events.push(msg);
  for (const fn of run.listeners) fn(msg);
  if (type === "end") run.finished = true;
}

function streamRun(req, res, run) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  });
  res.flushHeaders?.();
  let sent = 0;
  const shouldDrop = DROP_ONCE && !run.dropped;
  const write = (msg) => {
    res.write(`data: ${JSON.stringify(msg)}\n\n`);
    sent++;
    if (msg.type === "end") {
      cleanup();
      res.end();
    } else if (shouldDrop && sent === 4) {
      run.dropped = true;
      cleanup();
      res.destroy();
    }
  };
  const ka = setInterval(() => res.write(": keep-alive\n\n"), 15000);
  const cleanup = () => {
    clearInterval(ka);
    run.listeners.delete(write);
  };
  for (const msg of run.events) {
    write(msg);
    if (res.destroyed || res.writableEnded) return;
  }
  if (run.finished) return;
  run.listeners.add(write);
  req.on("close", cleanup);
}

const RUN_FIELDS = ["id", "userId", "bugId", "agentRunId", "mode", "engine", "status", "solved", "bestNodeId", "nodes", "usage", "latencyMs", "prUrl", "createdAt", "completedAt"];
const publicRun = (r) => Object.fromEntries(RUN_FIELDS.map((k) => [k, r[k]]));

// ---------- routes ----------
async function handle(req, res) {
  cors(req, res);
  if (req.method === "OPTIONS") {
    res.writeHead(204);
    return res.end();
  }
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const p = url.pathname;
  const m = req.method;
  let match;

  if (p === "/health") return json(res, 200, { status: "ok", mock: true });

  // ----- auth -----
  if (m === "POST" && p === "/api/auth/signup") {
    const b = await readBody(req);
    if (!b) return err(res, 400, "invalid JSON body");
    if (!emailOk(b.email)) return err(res, 400, "a valid email is required");
    if (typeof b.password !== "string" || b.password.length < 8) return err(res, 400, "password must be at least 8 characters");
    if (typeof b.companyName !== "string" || !b.companyName.trim()) return err(res, 400, "company name is required");
    const email = b.email.toLowerCase();
    if (users.get(email)?.verified) return err(res, 409, "an account with this email already exists");
    const u = { id: rid(12), email, password: b.password, companyName: b.companyName.trim(), verified: false };
    users.set(email, u);
    usersById.set(u.id, u);
    return json(res, 201, { message: "account created, check your email for a verification code", user: userResponse(u) });
  }
  if (m === "POST" && p === "/api/auth/verify-otp") {
    const b = await readBody(req);
    if (!b || !emailOk(b.email) || !/^\d{6}$/.test(b.code || "")) return err(res, 400, "email and a 6-digit code are required");
    const u = users.get(b.email.toLowerCase());
    if (!u) return err(res, 404, "user not found");
    if (b.code !== "123456") return err(res, 400, "invalid verification code");
    u.verified = true;
    issueSession(res, u.id);
    return json(res, 200, { user: userResponse(u) });
  }
  if (m === "POST" && p === "/api/auth/resend-otp") {
    const b = await readBody(req);
    if (!b || !emailOk(b.email)) return err(res, 400, "a valid email is required");
    return json(res, 200, { message: "a new code has been sent" });
  }
  if (m === "POST" && p === "/api/auth/login") {
    const b = await readBody(req);
    if (!b || !emailOk(b.email) || !b.password) return err(res, 400, "email and password are required");
    const u = users.get(b.email.toLowerCase());
    if (!u || u.password !== b.password) return err(res, 401, "invalid email or password");
    if (!u.verified) return json(res, 403, { error: "please verify your email before signing in", code: "EMAIL_NOT_VERIFIED" });
    issueSession(res, u.id);
    return json(res, 200, { user: userResponse(u) });
  }
  if (m === "POST" && p === "/api/auth/refresh") {
    const tok = parseCookies(req)[REFRESH_COOKIE];
    const s = tok && refreshTokens.get(tok);
    if (!s || s.exp < Date.now()) {
      clearSession(res);
      return err(res, 401, "session expired, please sign in again");
    }
    refreshTokens.delete(tok);
    issueSession(res, s.userId);
    return json(res, 200, { message: "session refreshed" });
  }
  if (m === "POST" && p === "/api/auth/logout") {
    const c = parseCookies(req);
    refreshTokens.delete(c[REFRESH_COOKIE]);
    accessTokens.delete(c[ACCESS_COOKIE]);
    clearSession(res);
    return json(res, 200, { message: "logged out" });
  }
  if (m === "GET" && p === "/api/auth/me") {
    const u = authUser(req);
    if (!u) return err(res, 401, "not authenticated");
    return json(res, 200, { user: userResponse(u) });
  }

  // ----- guest demo -----
  if (m === "GET" && p === "/api/demo/bugs") return json(res, 200, BUGS.map(publicBug));
  if (m === "POST" && p === "/api/demo/runs") {
    const b = await readBody(req);
    const bug = b && getBug(b.bugId);
    if (!bug) return err(res, 400, "unknown bugId");
    const ip = req.socket.remoteAddress || "?";
    const hits = (demoHits.get(ip) || []).filter((ts) => ts > Date.now() - 3600_000);
    if (hits.length >= DEMO_LIMIT) {
      demoHits.set(ip, hits);
      return err(res, 429, `Demo limit reached (${DEMO_LIMIT} runs per hour). Sign up for more runs.`);
    }
    hits.push(Date.now());
    demoHits.set(ip, hits);
    const mode = ["paginate", "slugify"].includes(bug.id) ? "replay" : "fake";
    const run = createRun({ bug, engine: "graph", mode, guest: true });
    return json(res, 201, { runId: run.id, mode: run.mode, engine: run.engine });
  }
  if (m === "GET" && (match = p.match(/^\/api\/demo\/runs\/([^/]+)\/events$/))) {
    const run = runs.get(match[1]);
    if (!run || !run.guest) return err(res, 404, "run not found");
    return streamRun(req, res, run);
  }

  // ----- everything below needs auth -----
  if (!p.startsWith("/api/")) return err(res, 404, "not found");
  const user = authUser(req);
  if (!user) return err(res, 401, "not authenticated");

  if (m === "GET" && p === "/api/bugs") return json(res, 200, BUGS.map(publicBug));

  if (m === "POST" && p === "/api/runs") {
    const b = await readBody(req);
    const bug = b && getBug(b.bugId);
    if (!bug) return err(res, 400, "unknown bugId");
    const engine = b.engine === "loop" ? "loop" : "graph";
    let mode = "fake";
    let notice;
    if (b.replay) {
      if (["paginate", "slugify"].includes(bug.id)) mode = "replay";
      else notice = "No saved replay for this bug yet, so this run uses fake mode.";
    }
    const run = createRun({ bug, engine, mode, userId: user.id });
    return json(res, 201, { runId: run.id, mode, engine, ...(notice ? { notice } : {}) });
  }
  if (m === "GET" && p === "/api/runs") {
    const list = [...runs.values()].filter((r) => r.userId === user.id).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    return json(res, 200, list.map(publicRun));
  }
  if ((match = p.match(/^\/api\/runs\/([^/]+)(\/events|\/pr)?$/))) {
    const run = runs.get(match[1]);
    if (!run || run.userId !== user.id) return err(res, 404, "run not found");
    if (m === "GET" && !match[2]) return json(res, 200, publicRun(run));
    if (m === "GET" && match[2] === "/events") return streamRun(req, res, run);
    if (m === "POST" && match[2] === "/pr") {
      if (run.prUrl) return json(res, 200, { url: run.prUrl });
      if (!run.solved) return err(res, 400, "run is not solved, there is no fix to open a pull request for");
      await new Promise((r) => setTimeout(r, 700 * SPEED));
      const url = `https://github.com/patchloop-demo/demo-bugs/pull/${++prCounter}`;
      run.prUrl = url;
      run.events.push({ type: "pr", data: { url } });
      return json(res, 200, { url });
    }
  }

  if (m === "POST" && p === "/api/tokens") {
    const b = await readBody(req);
    const name = (b?.name || "").trim();
    if (!name) return err(res, 400, "token name is required");
    if (name.length > 64) return err(res, 400, "token name must be at most 64 characters");
    const raw = "plk_" + rid(20);
    const t = { id: rid(8), userId: user.id, name, prefix: raw.slice(0, 10), hash: sha(raw), createdAt: now(), lastUsedAt: null };
    apiTokens.set(t.id, t);
    return json(res, 201, { token: raw, id: t.id, name, prefix: t.prefix });
  }
  if (m === "GET" && p === "/api/tokens") {
    const list = [...apiTokens.values()]
      .filter((t) => t.userId === user.id)
      .map(({ id, name, prefix, createdAt, lastUsedAt }) => ({ id, name, prefix, createdAt, lastUsedAt }));
    return json(res, 200, list);
  }
  if (m === "DELETE" && (match = p.match(/^\/api\/tokens\/([^/]+)$/))) {
    const t = apiTokens.get(match[1]);
    if (!t || t.userId !== user.id) return err(res, 404, "token not found");
    apiTokens.delete(t.id);
    return json(res, 200, { message: "token revoked" });
  }

  return err(res, 404, "not found");
}

http
  .createServer((req, res) => {
    handle(req, res).catch((e) => {
      console.error("[mock] handler error:", e?.message);
      if (!res.headersSent) err(res, 500, "internal error");
    });
  })
  .listen(PORT, () => {
    console.log(`[mock] PatchLoop mock backend on http://localhost:${PORT} (origins: ${ORIGINS.join(", ")}, speed x${SPEED})`);
  });
