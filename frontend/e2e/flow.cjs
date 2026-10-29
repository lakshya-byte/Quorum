#!/usr/bin/env node
// Full product flow against the mock backend, driven in a real browser (Playwright + Chromium).
//
//   cd frontend && npm run build && npx next start -p 3000      # in one terminal
//   node e2e/flow.cjs [screenshot-dir]                          # starts the mock itself on :8080
//
// Walks: signup (OTP 123456) -> dashboard checklist -> /new without GitHub -> GitHub App install
// (mock) -> disconnect -> demo account -> Slack webhook + test + link code -> /new (repo, task, review,
// start) -> live run (mid-stream, then solved) -> PR card with checks -> ask for changes (follow-up run)
// -> Merge -> second run on a repo without CI (merge warning) -> dashboard history, bell, tokens, /try.
// Screenshots at 1440px and 375px go to the given directory (default e2e/screens, git-ignored).
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch {
  console.error("playwright is not installed: npm i -g playwright && npx playwright install chromium");
  process.exit(2);
}

const FRONT = process.env.FRONTEND_URL || "http://localhost:3000";
const API_PORT = Number(process.env.MOCK_PORT || 8080);
const OUT = path.resolve(process.argv[2] || path.join(__dirname, "screens"));
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  " + detail : ""}`);
};

async function startMock() {
  const child = spawn(process.execPath, [path.join(__dirname, "..", "mocks", "server.mjs")], {
    env: { ...process.env, MOCK_PORT: String(API_PORT), MOCK_GITHUB_APP: "1", MOCK_SPEED: process.env.MOCK_SPEED || "0.6", FRONTEND_ORIGIN: FRONT },
    stdio: "ignore",
  });
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`http://localhost:${API_PORT}/health`);
      if (r.ok) return child;
    } catch {}
    await new Promise((r) => setTimeout(r, 150));
  }
  child.kill();
  throw new Error("mock backend did not start (is port " + API_PORT + " busy?)");
}

(async () => {
  const mock = await startMock();
  const browser = await chromium.launch();
  let shotN = 0;
  const shot = async (page, name, tag) => {
    const file = path.join(OUT, `${String(++shotN).padStart(2, "0")}-${name}-${tag}.png`);
    await page.screenshot({ path: file, fullPage: true });
  };
  try {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const email = `e2e${Date.now()}@example.com`;

    // ---- landing + auth
    await page.goto(FRONT + "/");
    check("landing renders hero", await page.getByRole("heading", { level: 1 }).first().isVisible());
    await page.waitForTimeout(9500);
    await shot(page, "landing", "d");
    await page.goto(FRONT + "/signup");
    await shot(page, "signup", "d");
    await page.goto(FRONT + "/signin");
    await shot(page, "signin", "d");
    await page.goto(FRONT + "/signup");
    await page.fill("#corporate-email", email);
    await page.fill("#org-name", "Acme Robotics");
    await page.fill("#new-password", "correct-horse-1");
    await page.locator("form button[type=submit]").click();
    await page.fill("#otp-code", "123456");
    await page.locator("form button[type=submit]").click();
    await page.waitForURL("**/dashboard", { timeout: 10000 });
    check("signup + OTP lands on dashboard", true);

    // ---- dashboard onboarding + /new without GitHub
    await page.getByTestId("checklist").waitFor();
    check("onboarding checklist shown", await page.getByTestId("checklist").isVisible());
    await shot(page, "dashboard-empty", "d");
    await page.goto(FRONT + "/new");
    await page.getByText("Connect GitHub first").waitFor();
    check("/new asks to connect GitHub first", true);
    await shot(page, "new-no-github", "d");

    // ---- integrations: GitHub App install (mock), disconnect, demo
    await page.goto(FRONT + "/integrations");
    await page.getByTestId("gh-install").click();
    await page.waitForURL("**/integrations?github=connected", { timeout: 10000 });
    await page.getByTestId("repo-count").waitFor();
    check("GitHub App install connects (mock)", (await page.getByTestId("repo-count").innerText()) === "3");
    await page.getByRole("button", { name: "Disconnect" }).click();
    await page.getByTestId("gh-demo").click();
    await page.getByText("Demo (offline)").waitFor();
    check("demo account connects", true);

    // ---- Slack
    await page.getByTestId("slack-input").fill("not-a-slack-url");
    await page.getByTestId("slack-save").click();
    await page.getByText("must start with https://hooks.slack.com/").first().waitFor();
    check("Slack webhook validation", true);
    await page.getByTestId("slack-input").fill("https://hooks.slack.com/services/T000/B000/abcdefghijklmnop");
    await page.getByTestId("slack-save").click();
    await page.getByTestId("slack-masked").waitFor();
    await page.getByTestId("slack-test").click();
    await page.getByText("Test message sent to Slack.").waitFor();
    check("Slack webhook saved and tested", true);
    await page.getByTestId("slack-code-btn").click();
    const code = await page.getByTestId("slack-code").innerText();
    check("Slack link code shown", /^[0-9A-F]{6}$/.test(code), code);
    await shot(page, "integrations", "d");

    // ---- /new: three steps
    await page.goto(FRONT + "/new");
    await page.locator('[data-repo="demo/inventory-api"]').click();
    await shot(page, "new-1-repo", "d");
    await page.getByTestId("next").click();
    await page.getByTestId("task-input").fill("Reserving the last unit of an item fails with 'out of stock'.");
    await shot(page, "new-2-task", "d");
    await page.getByTestId("next").click();
    await page.getByTestId("step-review").waitFor();
    await shot(page, "new-3-review", "d");
    await page.getByTestId("start-task").click();
    await page.waitForURL(/\/runs\//, { timeout: 10000 });
    const run1 = page.url().split("/runs/")[1];

    // ---- live run
    await page.getByTestId("pipeline").waitFor();
    await page.waitForSelector('[data-stage="propose"][data-state="active"], [data-stage="propose"][data-state="done"]', { timeout: 20000 });
    await shot(page, "run-live", "d");
    check("live pipeline and attempt tree render", (await page.locator("[data-node-id]").count()) > 0);
    await page.getByTestId("run-result").waitFor({ timeout: 40000 });
    check("run solved", (await page.getByTestId("run-result").innerText()).includes("Fixed"));
    await page.getByTestId("pr-card").waitFor({ timeout: 15000 });
    check("PR card appears", true);
    check("merge disabled while checks run", await page.getByTestId("merge-btn").isDisabled());
    check("merge disabled reason shown", (await page.getByTestId("merge-reason").innerText()).includes("Checks are still running"));
    await shot(page, "run-pr-pending", "d");
    // diff viewer for the multi-file winner
    await page.locator("[data-node-id]").last().click();
    await page.getByTestId("diff-body").waitFor();
    const tabs = await page.getByRole("tablist", { name: "Changed files" }).count();
    check("multi-file diff viewer", tabs > 0);
    await shot(page, "run-diff", "d");
    await page.keyboard.press("Escape");
    check("Slack indicator after finish", (await page.getByTestId("slack-indicator").innerText()).includes("Slack notified"));

    // ---- ask for changes -> follow-up run on the same PR
    await page.getByTestId("changes-toggle").click();
    await page.fill("#followup", "Also add a test for releasing more than reserved.");
    await page.getByTestId("changes-send").click();
    await page.waitForURL((u) => /\/runs\//.test(u.pathname) && !u.pathname.endsWith(run1), { timeout: 10000 });
    await page.getByText("Pull request updated").waitFor({ timeout: 40000 });
    check("follow-up updates the same PR", true);
    await shot(page, "run-followup", "d");

    // ---- merge on the original run (checks pass after a few seconds)
    await page.goto(FRONT + "/runs/" + run1);
    await page.getByTestId("pr-card").waitFor();
    await page.waitForFunction(() => !document.querySelector('[data-testid="merge-btn"]')?.disabled, null, { timeout: 20000 });
    check("merge enabled once checks pass", true);
    await page.getByTestId("merge-btn").click();
    await page.getByTestId("merge-confirm").click();
    await page.getByTestId("merged-note").waitFor();
    check("merge completes (human action)", true);
    await shot(page, "run-merged", "d");

    // ---- second run on a repo with no CI: warning
    await page.goto(FRONT + "/new");
    await page.locator('[data-repo="demo/text-tools"]').click();
    await page.getByTestId("next").click();
    await page.getByTestId("task-input").fill("word_count is wrong when words are separated by several spaces.");
    await page.getByTestId("next").click();
    await page.getByTestId("start-task").click();
    await page.waitForURL(/\/runs\//);
    await page.getByTestId("pr-card").waitFor({ timeout: 40000 });
    await page.getByText("This repository has no CI checks").waitFor();
    check("no-CI warning shown", true);

    // ---- dashboard, bell, tokens, try
    await page.goto(FRONT + "/dashboard");
    await page.getByTestId("runs-table").waitFor();
    check("dashboard lists runs", (await page.locator("[data-testid=runs-table] tbody tr").count()) >= 3);
    await shot(page, "dashboard", "d");
    await page.keyboard.press("Control+k");
    await page.getByRole("dialog", { name: "Command palette" }).waitFor();
    await page.keyboard.type("integr");
    await page.keyboard.press("Enter");
    await page.waitForURL("**/integrations");
    check("command palette navigates", true);
    await page.goto(FRONT + "/dashboard");
    await page.getByTestId("runs-table").waitFor();
    await page.getByTestId("bell").click();
    check("notifications present", (await page.getByText("Pull request opened").count()) > 0);
    await shot(page, "bell", "d");
    await page.goto(FRONT + "/settings/tokens");
    await page.getByTestId("token-name").fill("laptop");
    await page.getByTestId("token-create").click();
    await page.getByTestId("new-token").waitFor();
    check("API token created", true);
    await shot(page, "tokens", "d");
    check("no page errors (desktop)", errors.length === 0, errors.join(" | "));

    // ---- mobile pass with the same session
    const state = await ctx.storageState();
    const m = await browser.newContext({ viewport: { width: 375, height: 812 }, storageState: state });
    const mp = await m.newPage();
    const merrors = [];
    mp.on("pageerror", (e) => merrors.push(e.message));
    const overflow = async (name) => {
      const w = await mp.evaluate(() => document.documentElement.scrollWidth);
      check(`no horizontal scroll at 375px: ${name}`, w <= 376, `scrollWidth=${w}`);
    };
    for (const [name, url] of [
      ["landing", "/"],
      ["signin", "/signin"],
      ["dashboard", "/dashboard"],
      ["integrations", "/integrations"],
      ["run-finished", "/runs/" + run1],
      ["tokens", "/settings/tokens"],
    ]) {
      await mp.goto(FRONT + url);
      await mp.waitForTimeout(name === "landing" ? 9500 : 1200);
      await overflow(name);
      await shot(mp, name, "m");
    }
    await mp.goto(FRONT + "/new");
    await mp.locator('[data-repo="demo/billing-utils"]').click();
    await overflow("new-1");
    await shot(mp, "new-1-repo", "m");
    await mp.getByTestId("next").click();
    await mp.getByTestId("task-input").fill("Invoice totals lose their cents.");
    await shot(mp, "new-2-task", "m");
    await mp.getByTestId("next").click();
    await shot(mp, "new-3-review", "m");
    await mp.getByTestId("start-task").click();
    await mp.waitForURL(/\/runs\//);
    await mp.waitForSelector('[data-stage="locate"][data-state="done"]', { timeout: 20000 });
    await shot(mp, "run-live", "m");
    await overflow("run-live");
    await mp.getByTestId("run-result").waitFor({ timeout: 40000 });
    await shot(mp, "run-done", "m");
    await mp.goto(FRONT + "/try");
    await overflow("try");
    check("no page errors (mobile)", merrors.length === 0, merrors.join(" | "));
    await m.close();
    await ctx.close();
  } catch (e) {
    check("flow completed", false, String(e && e.message ? e.message.split("\n")[0] : e));
  } finally {
    await browser.close();
    mock.kill();
  }
  const failed = results.filter((x) => !x).length;
  console.log(`\n${results.length - failed}/${results.length} checks passed; screenshots in ${OUT}`);
  process.exit(failed ? 1 : 0);
})();
