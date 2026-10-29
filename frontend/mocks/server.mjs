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
//   MOCK_GITHUB_APP  "1" = GET /api/github/connect returns a mock install URL (else 503 "not configured")
//   MOCK_DROP_ONCE   "1" = cut each run's first stream after the 4th event (tests reconnect)
//
// Any OTP code "123456" verifies. Emails are never logged.

import http from "node:http";
import crypto from "node:crypto";
import { BUGS, getBug, publicBug } from "./bugs.mjs";
import { DEMO_REPOS, repoByName, candidateFiles, candidateDiff } from "./repos.mjs";

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
const github = new Map(); // userId -> { mode, login }
const slackHooks = new Map(); // userId -> webhook url
const slackLog = []; // messages the mock "sent"
const notifications = []; // { id, userId, kind, title, body, runId, read, createdAt }
const installStates = new Map(); // state -> userId
const taskHits = new Map(); // userId -> [timestamps]
const PUBLIC_BASE = process.env.MOCK_PUBLIC_URL || `http://localhost:${process.env.MOCK_PORT || 8080}`;
const FRONTEND = process.env.FRONTEND_URL || (process.env.FRONTEND_ORIGIN || "http://localhost:3000").split(",")[0].trim();

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
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
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


// ---------- repo runs (contract: repo flow) ----------
function repoOutput(repo, failing, names) {
  const total = repo.total;
  const dots = Array.from({ length: total }, (_, i) => (i < failing ? "F" : ".")).join("");
  const fails = failing ? `\n${"=".repeat(70)}\nFAIL: ${names || "test_case"}\nAssertionError: expected value did not match\n` : "";
  return `${dots}${fails}\n${"-".repeat(70)}\nRan ${total} tests in 0.00${3 + failing}s\n\n${failing ? `FAILED (failures=${failing})` : "OK"}`;
}

function buildRepoScript(repo, branch, run, opts = {}) {
  const s = SPEED;
  const ev = [];
  let t = 0;
  const push = (gap, type, data) => {
    t += Math.round(gap * s);
    ev.push({ at: t, type, data });
  };
  const nano = "nemotron-nano (Nebius Token Factory)";
  const sup = "nemotron-super (Nebius Token Factory)";
  const primary = (files) => files[Object.keys(files).find((p) => !p.startsWith("tests/"))];
  let tokens = 0;
  const nodeOf = (id, parent, depth, c, base) => {
    const files = c ? candidateFiles(repo, c) : repo.files;
    const blocked = c?.blocked;
    const failing = c ? c.failing ?? 0 : repo.repro.failing;
    const tk = id === 0 ? 0 : 1100 + ((id * 173) % 700);
    tokens += tk;
    return {
      id,
      parent,
      depth,
      idea: c ? c.idea : "Original code",
      strategy: c ? repo.strategies[(id - 1) % 3] : null,
      code: primary(files),
      files,
      diff: c ? candidateDiff(repo, c) : "",
      output: blocked ? `Blocked by the policy gate before execution.\n${blocked.map((r) => `- ${r}`).join("\n")}` : repoOutput(repo, failing, repo.repro.test_name),
      passed: blocked ? 0 : repo.total - failing,
      total: repo.total,
      score: blocked ? 0 : Math.round(((repo.total - failing) / repo.total - 0.002 * (c ? Object.keys(c.edits).length : 0)) * 1000) / 1000,
      model: id === 0 ? null : depth > 1 ? sup : nano,
      latency_ms: id === 0 ? 520 : 2100 + ((id * 311) % 2300),
      tokens: tk,
      policy: blocked ? { ok: false, reasons: blocked } : { ok: true, reasons: [] },
      security: c?.security
        ? { ok: false, new_findings: [{ rule: "B307", severity: "MEDIUM", message: "Use of possibly insecure function: eval()", line: 14 }] }
        : { ok: true, new_findings: [] },
      base,
    };
  };
  const clean = (n) => {
    const { base, ...rest } = n;
    void base;
    return rest;
  };

  push(0, "run_started", { run_id: run.id, bug_id: "", mode: "fake", engine: "graph" });
  push(120, "repo", { full_name: repo.fullName, branch, files: Object.keys(repo.files).length, language: repo.language, test_command: "python -m unittest", truncated: false });
  push(160, "guard", { stage: "input", verdict: "pass", reasons: [], latency_ms: 88 });
  push(520, "locate", { files: repo.locate });
  if (opts.followup) {
    push(300, "triage", { cause: `Follow-up request: ${opts.followup}`, strategies: ["Apply the requested change on top of the earlier patch", "Re-run the reproducer and full suite", "Keep the diff small"] });
    push(200, "node", clean(nodeOf(0, null, 0, null)));
    push(150, "round", { depth: 1 });
    const win = repo.candidates.find((c) => c.id === repo.winner);
    const n = nodeOf(1, 0, 1, win);
    n.idea = `Follow-up: ${opts.followup.slice(0, 80)}`;
    push(1100, "node", clean(n));
    push(250, "critic", { node_id: 1, lesson: "Reproducer and the existing suite both pass on top of the earlier patch." });
    push(200, "guard", { stage: "output", verdict: "pass", reasons: [], latency_ms: 120 });
    push(200, "done", { solved: true, best: 1, usage: { prompt_tokens: Math.round(tokens * 0.8), completion_tokens: Math.round(tokens * 0.2) }, latency_ms: t + 200, time_to_first_node_ms: 900 });
    push(500, "pr", { url: opts.prUrl, branch: opts.prBranch, number: opts.prNumber, fake: true, updated: true });
    push(10, "end", {});
    return ev;
  }
  push(780, "repro", {
    path: repo.repro.path,
    test_name: repo.repro.test_name,
    failed_on_original: true,
    output_tail: repoOutput(repo, repo.repro.failing, repo.repro.test_name).split("\n").slice(-8).join("\n"),
  });
  push(260, "triage", { cause: repo.cause, strategies: repo.strategies });
  push(250, "node", clean(nodeOf(0, null, 0, null)));

  let winnerNode = null;
  const rounds = [...new Set(repo.candidates.map((c) => c.parent))];
  let depth = 0;
  for (const parent of rounds) {
    if (winnerNode) break;
    depth += 1;
    push(220, "round", { depth });
    for (const c of repo.candidates.filter((x) => x.parent === parent)) {
      if (winnerNode) break;
      const n = nodeOf(c.id, c.parent, depth, c);
      push(depth === 1 ? 760 : 1000, "node", clean(n));
      if (c.id === repo.winner) {
        winnerNode = n;
        push(200, "critic", { node_id: c.id, lesson: "Reproducer and the existing suite both pass with the smallest diff and a clean security scan. Remaining candidates cancelled." });
      } else if (c.blocked) {
        push(150, "critic", { node_id: c.id, lesson: "Blocked before execution: patches may not touch CI configuration." });
      } else if (c.security) {
        push(150, "critic", { node_id: c.id, lesson: "Passes tests but introduces eval(); the security scan flags it. Prefer a plain comparison." });
      } else if ((c.failing ?? 0) > 0) {
        push(150, "critic", { node_id: c.id, lesson: parent === 0 && c.label === "partial" ? "Fixes the reported symptom but another test still fails. Keep this patch and extend it." : "Does not fix the failing test. Drop this direction." });
      }
    }
  }
  push(200, "guard", { stage: "policy", verdict: "pass", reasons: ["Winner touches only existing source files"], latency_ms: 5 });
  push(220, "guard", { stage: "output", verdict: "pass", reasons: [], latency_ms: 131 });
  push(200, "done", {
    solved: true,
    best: winnerNode.id,
    usage: { prompt_tokens: Math.round(tokens * 0.78), completion_tokens: Math.round(tokens * 0.22) },
    latency_ms: t + 200,
    time_to_first_node_ms: 1900,
  });
  if (run.autoPr) {
    const number = ++prCounter;
    const prBranch = `patchloop/${run.task.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 32)}-${Math.floor(Date.now() / 1000)}`;
    push(650, "pr", { url: `https://github.com/${repo.fullName}/pull/${number}`, branch: prBranch, number, fake: true });
    if (slackHooks.has(run.userId)) push(250, "slack", { sent: true });
  }
  push(20, "end", {});
  return ev;
}

function prStatus(run) {
  const pr = run.pr;
  if (!pr) return null;
  const age = Date.now() - pr.createdAt;
  let checks;
  if (run.repo === "demo/text-tools") checks = { state: "none", failing: [] };
  else if (run.repo === "demo/inventory-api" && age < 6000 * SPEED) checks = { state: "pending", failing: [] };
  else checks = { state: "success", failing: [] };
  const open = !run.merged;
  let reason = "";
  let allowed = open;
  if (!open) reason = "Already merged.";
  else if (checks.state === "pending") (allowed = false), (reason = "Checks are still running. Merge unlocks when they pass.");
  else if (checks.state === "failure") (allowed = false), (reason = "A required check is failing.");
  return {
    url: pr.url,
    number: pr.number,
    state: open ? "open" : "merged",
    mergeable: true,
    checks,
    mergeAllowed: allowed,
    reason,
    merged: run.merged || null,
  };
}

function createRepoRun({ repo, branch, task, userId, autoPr = true, parent, followup, source = "web" }) {
  const id = rid(12);
  const run = {
    id,
    userId,
    bugId: "",
    agentRunId: "ag_" + rid(6),
    mode: "fake",
    engine: "graph",
    status: "running",
    solved: false,
    bestNodeId: null,
    nodes: [],
    usage: { prompt_tokens: 0, completion_tokens: 0 },
    latencyMs: null,
    prUrl: parent?.prUrl || null,
    createdAt: now(),
    completedAt: null,
    kind: "repo",
    repo: repo.fullName,
    branch,
    task,
    autoPr,
    source,
    prNumber: parent?.prNumber ?? null,
    prBranch: parent?.prBranch ?? null,
    parentRunId: parent?.id ?? null,
    filesChanged: null,
    merged: null,
    cost: { tokens: 0, usd: null },
    safety: { policy: "pass", security: "pass", guard: "pass" },
    traceId: "tr_" + rid(6),
    langsmithUrl: null,
    pr: parent?.pr ?? null,
    events: [],
    listeners: new Set(),
    finished: false,
    dropped: false,
  };
  runs.set(id, run);
  const script = buildRepoScript(repo, branch, run, followup ? { followup, prUrl: parent.prUrl, prBranch: parent.prBranch, prNumber: parent.prNumber } : {});
  for (const e of script) {
    setTimeout(() => {
      if (e.type === "pr") {
        run.pr = run.pr ? { ...run.pr } : { url: e.data.url, number: e.data.number, branch: e.data.branch, createdAt: Date.now() };
        run.prNumber = e.data.number;
        run.prBranch = e.data.branch;
        if (!parent) addNote(userId, "pr", "Pull request opened", `${repo.fullName} #${e.data.number} is ready for review`, id);
        else addNote(userId, "pr", "Pull request updated", `${repo.fullName} #${e.data.number} has a new commit`, id);
      }
      if (e.type === "slack") slackLog.push({ at: now(), kind: "run-complete", runId: id, repo: repo.fullName, prUrl: run.prUrl });
      if (e.type === "done") {
        const n = run.nodes.find((x) => x.id === e.data.best);
        run.filesChanged = n?.files ? Object.keys(n.files).filter((p) => n.files[p] !== repo.files[p]).length : null;
        run.cost = { tokens: (e.data.usage.prompt_tokens || 0) + (e.data.usage.completion_tokens || 0), usd: null };
      }
      emit(run, e.type, e.data);
    }, e.at);
  }
  return run;
}

function addNote(userId, kind, title, body, runId) {
  notifications.unshift({ id: rid(6), userId, kind, title, body, runId, read: false, createdAt: now() });
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

const RUN_FIELDS = ["id", "userId", "bugId", "agentRunId", "mode", "engine", "status", "solved", "bestNodeId", "nodes", "usage", "latencyMs", "prUrl", "createdAt", "completedAt", "kind", "repo", "branch", "task", "source", "prNumber", "prBranch", "parentRunId", "filesChanged", "merged", "cost", "safety", "traceId", "langsmithUrl"];
const publicRun = (r) => Object.fromEntries(RUN_FIELDS.map((k) => [k, r[k] === undefined ? null : r[k]]).map(([k, v]) => [k, k === "kind" && v === null ? "bug" : v]));

function maskHook(u) {
  return u.slice(0, 27) + "..." + u.slice(-4);
}

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


  // ----- github app install callback (public; state is bound to a user) -----
  if (m === "GET" && p === "/api/github/callback") {
    const uid = installStates.get(url.searchParams.get("state") || "");
    if (!uid) {
      res.writeHead(302, { Location: `${FRONTEND}/integrations?github=error&reason=bad_state` });
      return res.end();
    }
    installStates.delete(url.searchParams.get("state"));
    github.set(uid, { mode: "app", login: "mock-app-user", installationId: 4242 });
    res.writeHead(302, { Location: `${FRONTEND}/integrations?github=connected` });
    return res.end();
  }
  if (m === "GET" && p === "/__mock/slack") return json(res, 200, slackLog);

  // ----- everything below needs auth -----
  if (!p.startsWith("/api/")) return err(res, 404, "not found");
  const user = authUser(req);
  if (!user) return err(res, 401, "not authenticated");


  // ----- github -----
  const gh = github.get(user.id);
  const ghStatus = () => ({
    connected: !!gh,
    mode: gh?.mode ?? null,
    login: gh?.login ?? null,
    avatarUrl: null,
    installationId: gh?.installationId ?? null,
    appConfigured: process.env.MOCK_GITHUB_APP === "1",
    repoCount: gh ? DEMO_REPOS.length : 0,
  });
  if (m === "GET" && p === "/api/github/status") return json(res, 200, ghStatus());
  if (m === "GET" && p === "/api/github/connect") {
    if (process.env.MOCK_GITHUB_APP !== "1") return err(res, 503, "github app not configured");
    const st = rid(10);
    installStates.set(st, user.id);
    return json(res, 200, { url: `${PUBLIC_BASE}/api/github/callback?installation_id=4242&setup_action=install&state=${st}` });
  }
  if (m === "POST" && p === "/api/github/demo") {
    github.set(user.id, { mode: "demo", login: "demo-user", installationId: null });
    return json(res, 200, { ...ghStatus(), connected: true, mode: "demo", login: "demo-user", repoCount: DEMO_REPOS.length });
  }
  if (m === "DELETE" && p === "/api/github") {
    github.delete(user.id);
    return json(res, 200, { message: "disconnected" });
  }
  if (m === "GET" && p === "/api/github/repos") {
    if (!gh) return err(res, 409, "connect github first");
    const q = (url.searchParams.get("q") || "").toLowerCase();
    return json(
      res,
      200,
      DEMO_REPOS.filter((r) => r.fullName.includes(q) || r.description.toLowerCase().includes(q)).map((r, i) => ({
        fullName: r.fullName,
        private: false,
        defaultBranch: "main",
        description: r.description,
        language: r.language,
        updatedAt: new Date(Date.now() - (i + 1) * 86400000 * 3).toISOString(),
      }))
    );
  }
  if (m === "GET" && (match = p.match(/^\/api\/github\/repos\/([^/]+)\/([^/]+)\/branches$/))) {
    if (!gh) return err(res, 409, "connect github first");
    if (!repoByName(`${match[1]}/${match[2]}`)) return err(res, 404, "repository not found or not granted to the app");
    return json(res, 200, [{ name: "main", default: true }, { name: "develop", default: false }]);
  }

  // ----- slack -----
  if (p === "/api/settings/slack") {
    if (m === "GET") return json(res, 200, { configured: slackHooks.has(user.id), webhookUrlMasked: slackHooks.has(user.id) ? maskHook(slackHooks.get(user.id)) : null });
    if (m === "PUT") {
      const b = await readBody(req);
      if (!b || typeof b.webhookUrl !== "string" || !/^https:\/\/hooks\.slack\.com\//.test(b.webhookUrl)) return err(res, 400, "webhook URL must start with https://hooks.slack.com/");
      slackHooks.set(user.id, b.webhookUrl);
      return json(res, 200, { configured: true, webhookUrlMasked: maskHook(b.webhookUrl) });
    }
    if (m === "DELETE") {
      slackHooks.delete(user.id);
      return json(res, 200, { configured: false });
    }
  }
  if (m === "POST" && p === "/api/settings/slack/test") {
    if (!slackHooks.has(user.id)) return err(res, 409, "set a Slack webhook first");
    slackLog.push({ at: now(), kind: "test" });
    return json(res, 200, { message: "test message sent" });
  }
  if (m === "POST" && p === "/api/slack/link-code") {
    const code = rid(3).toUpperCase();
    return json(res, 200, { code, expiresAt: new Date(Date.now() + 10 * 60000).toISOString() });
  }

  // ----- notifications -----
  if (m === "GET" && p === "/api/notifications") return json(res, 200, notifications.filter((n) => n.userId === user.id).slice(0, 30));
  if (m === "POST" && (match = p.match(/^\/api\/notifications\/([^/]+)\/read$/))) {
    const n = notifications.find((x) => x.id === match[1] && x.userId === user.id);
    if (n) n.read = true;
    return json(res, 200, { ok: true });
  }

  // ----- tasks (repo runs) -----
  if (m === "POST" && p === "/api/tasks") {
    const b = await readBody(req);
    if (!b) return err(res, 400, "invalid JSON body");
    if (!gh) return err(res, 409, "connect github first");
    const repo = repoByName(b.repo);
    if (!repo) return err(res, 404, "repository not found or not granted to the app");
    const task = typeof b.task === "string" ? b.task.trim() : "";
    if (!task) return err(res, 400, "describe the problem to fix");
    if (task.length > 4000) return err(res, 400, "task must be at most 4000 characters");
    const hits = (taskHits.get(user.id) || []).filter((ts) => ts > Date.now() - 3600_000);
    if (hits.length >= 10) return err(res, 429, "Task limit reached (10 per hour).");
    hits.push(Date.now());
    taskHits.set(user.id, hits);
    const run = createRepoRun({ repo, branch: b.branch || "main", task, userId: user.id, autoPr: b.autoPr !== false });
    return json(res, 201, { runId: run.id });
  }

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
  if ((match = p.match(/^\/api\/runs\/([^/]+)(\/events|\/pr|\/merge|\/followup)?$/))) {
    const run = runs.get(match[1]);
    if (!run || run.userId !== user.id) return err(res, 404, "run not found");
    const sub = match[2];
    if (m === "GET" && !sub) return json(res, 200, publicRun(run));
    if (m === "GET" && sub === "/events") return streamRun(req, res, run);
    if (m === "GET" && sub === "/pr") {
      const st = prStatus(run);
      if (!st) return err(res, 404, "this run has no pull request");
      return json(res, 200, st);
    }
    if (m === "POST" && sub === "/merge") {
      const st = prStatus(run);
      if (!st) return err(res, 404, "this run has no pull request");
      if (!gh) return err(res, 409, "connect github first");
      if (!st.mergeAllowed) return json(res, 409, { error: st.reason || "merge not allowed" });
      run.merged = { by: gh.login, at: now() };
      addNote(user.id, "merged", "Pull request merged", `${run.repo} #${run.prNumber} was merged by you`, run.id);
      return json(res, 200, { merged: true, ...(st.checks.state === "none" ? { warning: "no checks configured" } : {}) });
    }
    if (m === "POST" && sub === "/followup") {
      const b = await readBody(req);
      const msg = typeof b?.message === "string" ? b.message.trim() : "";
      if (!msg) return err(res, 400, "message is required");
      if (!run.pr) return err(res, 409, "this run has no pull request to update");
      const n = [...runs.values()].filter((r) => r.parentRunId === run.id).length;
      if (n >= 5) return err(res, 429, "Follow-up limit reached (5 per run).");
      const child = createRepoRun({ repo: repoByName(run.repo), branch: run.branch, task: run.task, userId: user.id, parent: run, followup: msg });
      return json(res, 201, { runId: child.id });
    }
    if (m === "POST" && sub === "/pr") {
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
