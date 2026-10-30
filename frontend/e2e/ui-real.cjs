#!/usr/bin/env node
// Browser flow against the REAL stack (scripts/dev-up.sh: Mongo + Python agent + Go backend + Next.js),
// in fake mode with the offline demo GitHub account.
//
//   FRONTEND_MODE=prod scripts/dev-up.sh
//   node frontend/e2e/ui-real.cjs [screenshot-dir]
//
// Walks: signup -> OTP (read from the DEV_MODE endpoint, no email) -> dashboard checklist -> Integrations:
// connect the demo account -> /new (repo, task, review, start) -> live run page -> PR card -> Merge is
// disabled while the fake CI runs -> Merge click -> merged state -> dashboard history -> /try.
// Screenshots at 1440px and 375px go to the given directory (default .logs/screens-real).
// Needs the `playwright` package with Chromium (not a repo dependency).
const fs = require("node:fs");
const path = require("node:path");

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch {
  console.error("playwright is not installed: npm i -g playwright && npx playwright install chromium");
  process.exit(2);
}

const ROOT = path.resolve(__dirname, "..", "..");
const env = {};
try {
  for (const line of fs.readFileSync(path.join(ROOT, ".logs", "dev.env"), "utf8").split("\n")) {
    const m = line.match(/^([A-Z_]+)=(.*)$/);
    if (m) env[m[1]] = m[2];
  }
} catch {}
const SECRET = process.env.AGENT_SHARED_SECRET || env.AGENT_SHARED_SECRET;
const FRONT = process.env.FRONTEND_URL || "http://localhost:3000";
const BACK = process.env.BACKEND_URL || "http://localhost:8080";
const OUT = path.resolve(process.argv[2] || path.join(ROOT, ".logs", "screens-real"));
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  " + detail : ""}`);
};

async function devOtp(email) {
  for (let i = 0; i < 30; i++) {
    const r = await fetch(`${BACK}/internal/dev/otp?email=${encodeURIComponent(email)}`, { headers: { "X-Agent-Secret": SECRET } });
    if (r.ok) return (await r.json()).code;
    await new Promise((res) => setTimeout(res, 250));
  }
  throw new Error("no OTP for the new account (is the backend running with DEV_MODE=true?)");
}

(async () => {
  if (!SECRET) throw new Error("AGENT_SHARED_SECRET unknown (run scripts/dev-up.sh)");
  const browser = await chromium.launch();
  let n = 0;
  const shot = async (page, name, tag) => page.screenshot({ path: path.join(OUT, `${String(++n).padStart(2, "0")}-${name}-${tag}.png`), fullPage: true });
  try {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    globalThis.__page = page;
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => m.type() === "error" && !/favicon|Failed to load resource/.test(m.text()) && errors.push("console: " + m.text()));
    const email = `ui-real-${Date.now()}@example.com`;

    // ---- landing + signup + OTP
    await page.goto(FRONT + "/");
    check("landing renders", await page.getByRole("heading", { level: 1 }).first().isVisible());
    await page.waitForTimeout(9500);
    await shot(page, "landing", "d");
    await page.goto(FRONT + "/signup");
    await page.fill("#corporate-email", email);
    await page.fill("#org-name", "Acme Robotics");
    await page.fill("#new-password", "correct-horse-1");
    await page.locator("form button[type=submit]").click();
    const code = await devOtp(email);
    await page.fill("#otp-code", code);
    await page.locator("form button[type=submit]").click();
    await page.waitForURL("**/dashboard", { timeout: 15000 });
    check("signup + OTP (real backend) lands on dashboard", true);
    await page.getByTestId("checklist").waitFor();
    check("onboarding checklist shown (GitHub not connected)", await page.getByTestId("checklist").isVisible());
    await shot(page, "dashboard-empty", "d");
    await page.goto(FRONT + "/new");
    await page.getByText("Connect GitHub first").waitFor();
    check("/new asks to connect GitHub first", true);

    // ---- integrations: the GitHub App is not configured here, the demo account is
    await page.goto(FRONT + "/integrations");
    await page.getByTestId("gh-demo").click();
    await page.getByText("Demo (offline)").waitFor();
    check("integrations: demo account connects", (await page.getByTestId("repo-count").innerText()) === "3");
    await shot(page, "integrations", "d");

    // ---- /new -> run
    await page.goto(FRONT + "/new");
    await page.locator('[data-repo="demo/shop-api"]').click();
    await shot(page, "new-1-repo", "d");
    await page.getByTestId("next").click();
    await page.getByTestId("task-input").fill("Checkout totals are wrong when a percentage coupon is used: the discount also reduces shipping and rounds down.");
    await page.getByTestId("next").click();
    await page.getByTestId("step-review").waitFor();
    await shot(page, "new-3-review", "d");
    await page.getByTestId("start-task").click();
    await page.waitForURL(/\/runs\//, { timeout: 15000 });
    const run1 = page.url().split("/runs/")[1];
    await page.getByTestId("pipeline").waitFor();
    await page.waitForSelector('[data-stage="propose"][data-state="active"], [data-stage="propose"][data-state="done"]', { timeout: 30000 });
    await shot(page, "run-live", "d");
    check("live pipeline and attempt tree render from the real agent stream", (await page.locator("[data-node-id]").count()) > 0);
    await page.getByTestId("run-result").waitFor({ timeout: 60000 });
    check("run solved (real agent, fake model)", (await page.getByTestId("run-result").innerText()).includes("Fixed"));
    await page.getByTestId("pr-card").waitFor({ timeout: 20000 });
    check("PR card appears", true);
    check("files changed stat shows 2", /Files changed\s*2/.test((await page.getByTestId("status-card").innerText()).replace(/\n/g, " ")));

    // fake CI is pending for a few seconds after the run: Merge must be disabled with the reason
    const disabledFirst = await page.getByTestId("merge-btn").isDisabled();
    if (disabledFirst) {
      check("merge disabled while checks run, with a reason", (await page.getByTestId("merge-reason").innerText()).toLowerCase().includes("checks are still running"));
      await shot(page, "run-pr-pending", "d");
    } else {
      check("merge disabled while checks run, with a reason", false, "checks were already green when the card loaded");
    }
    await page.waitForFunction(() => !document.querySelector('[data-testid="merge-btn"]')?.disabled, null, { timeout: 30000 });
    check("merge enabled once the checks pass (card polls)", true);

    // diff viewer for the multi-file winner
    await page.locator("[data-node-id]", { hasText: /winner/i }).first().click();
    await page.getByTestId("diff-body").waitFor();
    check("multi-file diff viewer", (await page.getByRole("tablist", { name: "Changed files" }).count()) > 0);
    await shot(page, "run-diff", "d");
    await page.keyboard.press("Escape");
    check("Slack indicator reads run.slackSent (no Slack here, so 'not set up')", (await page.getByTestId("slack-indicator").innerText()).toLowerCase().includes("slack"));

    await page.getByTestId("merge-btn").click();
    await page.getByTestId("merge-confirm").click();
    await page.getByTestId("merged-note").waitFor({ timeout: 15000 });
    check("Merge click -> merged state (human action, demo PR)", (await page.getByTestId("merged-note").innerText()).includes("Merged"));
    await shot(page, "run-merged", "d");

    // ---- dashboard history
    await page.goto(FRONT + "/dashboard");
    await page.getByTestId("runs-table").waitFor();
    const row = await page.locator("[data-testid=runs-table] tbody tr").first().innerText();
    check("dashboard lists the run with repo, tokens and safety", /shop-api/.test(row) && /tok/.test(row) && /all pass/.test(row), row.replace(/\s+/g, " ").slice(0, 120));
    check("dashboard shows merged state", /merged/i.test(row));
    await shot(page, "dashboard", "d");
    await page.getByTestId("bell").click();
    check("notifications bell shows PR opened and merged", (await page.getByText("Pull request opened").count()) > 0 && (await page.getByText("Pull request merged").count()) > 0);
    await shot(page, "bell", "d");
    check("no page errors (desktop)", errors.length === 0, errors.join(" | "));

    // ---- mobile pass, same session
    const state = await ctx.storageState();
    const m = await browser.newContext({ viewport: { width: 375, height: 812 }, storageState: state });
    const mp = await m.newPage();
    const merrors = [];
    mp.on("pageerror", (e) => merrors.push(e.message));
    const overflow = async (name) => {
      const w = await mp.evaluate(() => document.documentElement.scrollWidth);
      check(`no horizontal scroll at 375px: ${name}`, w <= 376, `scrollWidth=${w}`);
    };
    for (const [name, url] of [["landing", "/"], ["dashboard", "/dashboard"], ["integrations", "/integrations"], ["run-merged", "/runs/" + run1]]) {
      await mp.goto(FRONT + url);
      await mp.waitForTimeout(name === "landing" ? 9500 : 1500);
      await overflow(name);
      await shot(mp, name, "m");
    }
    await mp.goto(FRONT + "/new");
    await mp.locator('[data-repo="demo/wordstats"]').click();
    await mp.getByTestId("next").click();
    await mp.getByTestId("task-input").fill("Word counts are wrong: The and the are counted separately.");
    await mp.getByTestId("next").click();
    await shot(mp, "new-3-review", "m");
    await mp.getByTestId("start-task").click();
    await mp.waitForURL(/\/runs\//);
    await mp.waitForSelector('[data-stage="locate"][data-state="done"]', { timeout: 30000 });
    await shot(mp, "run-live", "m");
    await overflow("run-live");
    await mp.getByTestId("run-result").waitFor({ timeout: 60000 });
    await mp.getByTestId("pr-card").waitFor({ timeout: 20000 });
    await shot(mp, "run-done-pr", "m");
    await overflow("run-done");
    check("no page errors (mobile)", merrors.length === 0, merrors.join(" | "));
    await m.close();
    await ctx.close();
  } catch (e) {
    try { await globalThis.__page?.screenshot({ path: path.join(OUT, "failure.png"), fullPage: true }); } catch {}
    check("flow completed", false, String(e && e.message ? e.message.split("\n")[0] : e));
  } finally {
    await browser.close();
    const failed = results.filter((x) => !x).length;
    console.log(`\n${results.length - failed} PASS, ${failed} FAIL  (screenshots: ${OUT})`);
    process.exit(failed ? 1 : 0);
  }
})();
