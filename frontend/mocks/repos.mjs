// Demo repositories served by the mock backend (mirrors the three bundled agent demo repos in spirit).
// Each repo has original files, a bug description, and candidate patches used by the scripted repo run.

export function unifiedDiff(path, before, after, ctx = 3) {
  const A = before.replace(/\n$/, "").split("\n");
  const B = after.replace(/\n$/, "").split("\n");
  const n = A.length;
  const m = B.length;
  const lcs = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) lcs[i][j] = A[i] === B[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const ops = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) {
      ops.push([" ", A[i++]]);
      j++;
    }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) ops.push(["-", A[i++]]);
    else ops.push(["+", B[j++]]);
  }
  while (i < n) ops.push(["-", A[i++]]);
  while (j < m) ops.push(["+", B[j++]]);
  const changed = ops.map((o, k) => (o[0] !== " " ? k : -1)).filter((k) => k >= 0);
  if (!changed.length) return "";
  // group changes into hunks
  const hunks = [];
  let s = Math.max(0, changed[0] - ctx);
  let e = Math.min(ops.length, changed[0] + ctx + 1);
  for (const k of changed.slice(1)) {
    if (k - ctx <= e) e = Math.min(ops.length, k + ctx + 1);
    else {
      hunks.push([s, e]);
      s = Math.max(0, k - ctx);
      e = Math.min(ops.length, k + ctx + 1);
    }
  }
  hunks.push([s, e]);
  let out = `diff --git a/${path} b/${path}\n--- a/${path}\n+++ b/${path}\n`;
  for (const [hs, he] of hunks) {
    let a0 = 1;
    let b0 = 1;
    for (let k = 0; k < hs; k++) {
      if (ops[k][0] !== "+") a0++;
      if (ops[k][0] !== "-") b0++;
    }
    const seg = ops.slice(hs, he);
    const ac = seg.filter((o) => o[0] !== "+").length;
    const bc = seg.filter((o) => o[0] !== "-").length;
    out += `@@ -${a0},${ac} +${b0},${bc} @@\n` + seg.map((o) => o[0] + o[1]).join("\n") + "\n";
  }
  return out;
}

// The three repos are read from the agent's bundled demo repos (agent/app/demo_repos), so the mock
// backend, the real agent and the backend's demo list always agree. Candidate patches are the agent's
// own fixtures (fixes/wrong, fixes/partial, fixes/correct). Test counts below were measured with
// `python -m unittest discover` on baseline + reproducer, then with each fixture applied.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEMO_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../agent/app/demo_repos");

function readTree(dir, base = dir, out = {}) {
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "__pycache__") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) readTree(p, base, out);
    else out[path.relative(base, p).split(path.sep).join("/")] = fs.readFileSync(p, "utf8");
  }
  return out;
}

function demoRepo(name, extra) {
  const dir = path.join(DEMO_DIR, name);
  const meta = JSON.parse(fs.readFileSync(path.join(dir, "meta.json"), "utf8"));
  const files = { ...readTree(path.join(dir, "repo")), ...readTree(path.join(dir, "repro")) };
  const fix = (v) => readTree(path.join(dir, "fixes", v));
  const reproFile = Object.keys(readTree(path.join(dir, "repro")))[0];
  const testName = /def (test_\w+)/.exec(files[reproFile])?.[1] || "test_reproducer";
  return {
    fullName: `demo/${name}`,
    description: meta.description,
    language: "Python",
    total: extra.total,
    files,
    defaultTask: meta.default_task,
    locate: meta.locate,
    repro: { path: meta.repro_path, test_name: testName, failing: extra.baseFailing },
    cause: extra.cause,
    strategies: extra.strategies,
    candidates: [
      { id: 1, parent: 0, label: "wrong", idea: extra.ideas.wrong, override: fix("wrong"), failing: extra.failing.wrong },
      { id: 2, parent: 0, label: "partial", idea: extra.ideas.partial, override: fix("partial"), failing: extra.failing.partial },
      { id: 3, parent: 0, label: "policy", idea: "Patch and add a CI workflow that deploys", override: { ...fix("correct"), ".github/workflows/deploy.yml": "on: push\n" }, blocked: ["Touches .github/: workflows are off limits"] },
      { id: 4, parent: 2, label: "fix", idea: extra.ideas.fix, override: fix("correct"), failing: 0 },
    ],
    winner: 4,
  };
}

export const DEMO_REPOS = [
  demoRepo("shop-api", {
    total: 13,
    baseFailing: 5,
    cause: "Cart.total() applies the percentage coupon to items plus shipping, and apply_percent() truncates instead of rounding half up.",
    strategies: ["Round the discount half up in coupons.py", "Discount only the items, never shipping", "Rewrite total() around a single discount helper"],
    ideas: { wrong: "Skip the coupon when shipping is charged", partial: "Round the discount half up in coupons.py only", fix: "Round half up and keep shipping out of the discount (2 files)" },
    failing: { wrong: 6, partial: 3 },
  }),
  demoRepo("wordstats", {
    total: 12,
    baseFailing: 6,
    cause: "tokenize() keeps case and splits on apostrophes, and the counter and the report both build on it.",
    strategies: ["Lowercase tokens in tokenize()", "Keep apostrophes inside words with a regular expression", "Normalise in the counter instead of the tokenizer"],
    ideas: { wrong: "Split on every non-letter character", partial: "Lowercase tokens but keep splitting contractions", fix: "Lowercase and keep contractions whole" },
    failing: { wrong: 12, partial: 3 },
  }),
  demoRepo("booking", {
    total: 10,
    baseFailing: 2,
    cause: "overlaps() uses <= so intervals that only touch count as overlapping, and Calendar.book() relies on it.",
    strategies: ["Compare with < in overlaps()", "Treat intervals as half-open [start, end)", "Check conflicts in Calendar.book() only"],
    ideas: { wrong: "Never report overlaps", partial: "Fix one side of the comparison", fix: "Use half-open intervals in overlaps()" },
    failing: { wrong: 3, partial: 1 },
  }),
];

export function repoByName(name) {
  return DEMO_REPOS.find((r) => r.fullName === name);
}

export function candidateFiles(repo, c) {
  return { ...repo.files, ...(c.override || {}) };
}

export function candidateDiff(repo, c) {
  const after = candidateFiles(repo, c);
  return Object.keys(after)
    .filter((p) => after[p] !== repo.files[p])
    .map((p) => unifiedDiff(p, repo.files[p] ?? "", after[p]))
    .join("");
}
