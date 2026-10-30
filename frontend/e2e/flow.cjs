#!/usr/bin/env node
// Full product flow against the mock backend, driven in a real browser (Playwright + Chromium).
//
//   cd frontend
//   NEXT_PUBLIC_MOCK_AUTH=1 NEXT_PUBLIC_API_URL=http://localhost:8080 npm run build
//   NEXT_PUBLIC_MOCK_AUTH=1 npx next start -p 3000        # one terminal (no Clerk keys needed in mock-auth mode)
//   node e2e/flow.cjs [screenshot-dir]                    # starts the mock itself on :8080
//
// NEXT_PUBLIC_MOCK_AUTH=1 swaps Clerk for a bearer token in localStorage so this script can run offline.
// Production builds never set it; the Clerk sign-in pages are not exercised here.
//
// Walks: landing -> dashboard checklist -> GitHub connect (mock) -> Slack -> classic bug fix on /new (compact
// view, PR, follow-up, merge) -> UI task: /new type chips, swarm view live, gates, before/after compare,
// lightbox, logs, PR merge -> feature, refactor, partial, unsolvable runs -> needs_input answers -> dashboard
// -> mobile pass at 375px. Screenshots (1440 and 375) go to the given directory (default e2e/screens).
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch {
  console.error("playwright is not installed: npm i -g playwright && npx playwright install chromium (set NODE_PATH to its node_modules)");
  process.exit(2);
}

const FRONT = process.env.FRONTEND_URL || "http://localhost:3000";
const API_PORT = Number(process.env.MOCK_PORT || 8080);
const API = `http://localhost:${API_PORT}`;
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
      const r = await fetch(`${API}/health`);
      if (r.ok) return child;
    } catch {}
    await new Promise((r) => setTimeout(r, 150));
  }
  child.kill();
  throw new Error("mock backend did not start (is port " + API_PORT + " busy?)");
}

async function mockLogin(email) {
  const j = (p, body) => fetch(API + p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  await j("/api/auth/signup", { email, password: "correct-horse-1", companyName: "Acme Robotics" });
  const r = await (await j("/api/auth/verify-otp", { email, code: "123456" })).json();
  return r.token;
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
    const email = `e2e${Date.now()}@example.com`;
    const token = await mockLogin(email);
    const post = async (p, body) => (await fetch(API + p, { method: "POST", headers: { "content-type": "application/json", Authorization: "Bearer " + token }, body: JSON.stringify(body || {}) })).json();
    const get = async (p) => (await fetch(API + p, { headers: { Authorization: "Bearer " + token } })).json();
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx.addInitScript((t) => {
      try {
        localStorage.setItem("patchloop:mock-token", t);
      } catch {}
    }, token);
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));

    // ---- landing
    await page.goto(FRONT + "/");
    check("landing renders hero", await page.getByRole("heading", { level: 1 }).first().isVisible());
    check("hero states the broader product", (await page.locator("main").innerText()).includes("spawns a swarm sized to the task"));
    await page.getByTestId("live-demo").waitFor();
    await page.waitForFunction(() => document.querySelector('[data-testid="live-demo"] [data-stage="verify"][data-state="done"]'), null, { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(800);
    await shot(page, "landing", "d");
    await page.locator("#verification").scrollIntoViewIfNeeded();
    check("how verification works section", await page.locator("#verification").isVisible());

    // ---- dashboard onboarding + /new without GitHub
    await page.goto(FRONT + "/dashboard");
    await page.getByTestId("checklist").waitFor();
    check("onboarding checklist shown", await page.getByTestId("checklist").isVisible());
    await shot(page, "dashboard-empty", "d");
    await page.goto(FRONT + "/new");
    await page.getByText("Connect GitHub first").waitFor();
    check("/new asks to connect GitHub first", true);

    // ---- integrations: GitHub App install (mock), disconnect, demo
    await page.goto(FRONT + "/integrations");
    await page.getByTestId("gh-install").click();
    await page.waitForURL("**/integrations?github=connected", { timeout: 10000 });
    await page.getByTestId("repo-count").waitFor();
    check("GitHub App install connects (mock)", (await page.getByTestId("repo-count").innerText()) === "4");
    await page.getByRole("button", { name: "Disconnect" }).click();
    await page.getByTestId("gh-demo").click();
    await page.getByText("Demo (offline)").waitFor();
    check("demo account connects", true);

    // ---- Slack
    await page.getByTestId("slack-input").fill("not-a-slack-url");
    await page.getByTestId("slack-save").click();
    await page.getByText("must start with https://hooks.slack.com/").first().waitFor();
    await page.getByTestId("slack-input").fill("https://hooks.slack.com/services/T000/B000/abcdefghijklmnop");
    await page.getByTestId("slack-save").click();
    await page.getByTestId("slack-masked").waitFor();
    await page.getByTestId("slack-test").click();
    await page.getByText("Test message sent to Slack.").waitFor();
    check("Slack webhook saved and tested", true);

    // ---- classic bug fix: Auto resolves to the compact view
    await page.goto(FRONT + "/new");
    await page.locator('[data-repo="demo/shop-api"]').click();
    await page.getByTestId("next").click();
    await page.getByTestId("task-input").fill("Checkout totals are wrong when a percentage coupon is used.");
    await page.getByTestId("next").click();
    await page.getByTestId("step-review").waitFor();
    await page.getByTestId("start-task").click();
    await page.waitForURL(/\/runs\//, { timeout: 10000 });
    const run1 = page.url().split("/runs/")[1];
    await page.getByTestId("pipeline").waitFor();
    await page.waitForSelector('[data-stage="propose"][data-state="active"], [data-stage="propose"][data-state="done"]', { timeout: 20000 });
    await page.getByTestId("run-result").waitFor({ timeout: 40000 });
    check("bug fix keeps the compact view", (await page.getByTestId("swarm-view").count()) === 0 && (await page.locator("[data-node-id]").count()) > 0);
    check("bug fix solved", (await page.getByTestId("run-result").innerText()).includes("Fixed"));
    await page.getByTestId("pr-card").waitFor({ timeout: 15000 });
    check("merge disabled while checks run", await page.getByTestId("merge-btn").isDisabled());
    await shot(page, "run-bugfix", "d");
    await page.getByTestId("changes-toggle").click();
    await page.fill("#followup", "Also add a test for a coupon of 100 percent.");
    await page.getByTestId("changes-send").click();
    await page.waitForURL((u) => /\/runs\//.test(u.pathname) && !u.pathname.endsWith(run1), { timeout: 10000 });
    await page.getByText("Pull request updated").waitFor({ timeout: 40000 });
    check("follow-up updates the same PR", true);
    await page.goto(FRONT + "/runs/" + run1);
    await page.getByTestId("pr-card").waitFor();
    await page.waitForFunction(() => !document.querySelector('[data-testid="merge-btn"]')?.disabled, null, { timeout: 20000 });
    await page.getByTestId("merge-btn").click();
    await page.getByTestId("merge-confirm").click();
    await page.getByTestId("merged-note").waitFor();
    check("bug fix merge completes (human action)", true);

    // ---- UI task: /new type chips, then the swarm view
    await page.goto(FRONT + "/new");
    await page.locator('[data-repo="demo/react-todo"]').click();
    await page.getByTestId("next").click();
    await page.getByTestId("type-chips").waitFor();
    check("ten task-type chips", (await page.locator('input[name="task-type"]').count()) === 10);
    check("Auto is the default", await page.getByTestId("type-auto").isChecked());
    await page.getByTestId("type-ui").check({ force: true });
    check("how-it-is-verified follows the type", (await page.getByTestId("type-how").innerText()).includes("horizontal overflow"));
    await page.getByRole("button", { name: "Improve the UI of this React app" }).click();
    check("example fills the task", (await page.getByTestId("task-input").inputValue()) === "Improve the UI of this React app");
    await page.getByTestId("advanced").locator("summary").click();
    await page.getByTestId("limit-workers").fill("4");
    await shot(page, "new-2-task-ui", "d");
    await page.getByTestId("next").click();
    check("review shows the type", (await page.getByTestId("step-review").innerText()).includes("UI/UX"));
    await page.getByTestId("start-task").click();
    await page.waitForURL(/\/runs\//, { timeout: 10000 });
    const uiRun = page.url().split("/runs/")[1];
    await page.getByTestId("swarm-view").waitFor();
    await page.getByTestId("plan-card").waitFor({ timeout: 15000 });
    check("plan card shows type and hard/advisory criteria", (await page.getByTestId("plan-type").innerText()).includes("UI/UX") && (await page.getByTestId("plan-card").innerText()).includes("advisory"));
    await page.waitForSelector('[data-unit="u2"] [data-agent][data-status="running"]', { timeout: 30000 });
    check("agent lanes show variants running in parallel", (await page.locator('[data-agent][data-status="running"]').count()) >= 2);
    await shot(page, "swarm-live", "d");
    await page.getByTestId("run-result").waitFor({ timeout: 60000 });
    check("UI run complete", (await page.getByTestId("run-result").getAttribute("data-outcome")) === "complete");
    check("verification ran two rounds (repair after a failing hard gate)", (await page.getByTestId("rounds").locator("button").count()) === 2);
    check("9/9 hard gates", (await page.getByTestId("hard-count").innerText()).includes("9/9"));
    await page.getByTestId("rounds").locator("button").first().click();
    check("round 1 shows the failing overflow gate", (await page.locator('[data-criterion="ui_overflow"]:visible').first().getAttribute("data-status")) === "fail");
    await shot(page, "swarm-gates-round1", "d");
    await page.getByTestId("rounds").locator("button").last().click();
    check("merge conflict then resolved", (await page.getByTestId("merge-panel").innerText()).includes("conflict resolved"));
    await page.getByTestId("pr-card").waitFor({ timeout: 15000 });
    check("PR carries a commit per unit", (await page.getByTestId("pr-card").innerText()).includes("4 commits"));
    // artifacts: compare slider
    await page.getByTestId("compare-slider").waitFor();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="compare-slider"] img').length === 2, null, { timeout: 15000 });
    check("compare slider has alt text on both images", (await page.locator('[data-testid="compare-slider"] img[alt^="Before"]').count()) === 1 && (await page.locator('[data-testid="compare-slider"] img[alt^="After"]').count()) === 1);
    const range = page.getByTestId("compare-range");
    await range.focus();
    await page.keyboard.press("ArrowRight");
    check("slider is keyboard operable", (await range.inputValue()) === "51");
    await range.fill("20");
    await page.getByRole("tab", { name: /768px/ }).click();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="compare-slider"] img').length === 2);
    await page.getByRole("tab", { name: /375px/ }).click();
    await page.getByRole("button", { name: "Side by side" }).click();
    await page.getByTestId("side-by-side").waitFor();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="side-by-side"] img').length === 2, null, { timeout: 15000 });
    await shot(page, "artifacts-side", "d");
    await page.getByRole("button", { name: "Slider" }).click();
    await page.getByTestId("enlarge").click();
    await page.getByTestId("lightbox").waitFor();
    check("lightbox opens as a modal dialog", (await page.getByRole("dialog").count()) === 1);
    await page.keyboard.press("Escape");
    await page.getByTestId("lightbox").waitFor({ state: "detached" });
    check("Escape closes the lightbox", true);
    await page.getByTestId("artifact-files").getByRole("button", { name: "View" }).first().click();
    await page.getByTestId("log-viewer").waitFor();
    check("log viewer shows text", (await page.getByTestId("log-viewer").innerText()).length > 20);
    await page.getByTestId("artifacts").scrollIntoViewIfNeeded();
    await shot(page, "artifacts-compare", "d");
    // diff per unit
    await page.getByTestId("diff-panel").getByRole("tab", { name: "Unit u1" }).click();
    await page.getByTestId("diff-body").waitFor();
    check("per-unit diff viewer", true);
    // merge
    await page.waitForFunction(() => !document.querySelector('[data-testid="merge-btn"]')?.disabled, null, { timeout: 20000 });
    await page.getByTestId("merge-btn").click();
    await page.getByTestId("merge-confirm").click();
    await page.getByTestId("merged-note").waitFor();
    check("UI run merge completes (human action)", true);
    await page.goto(FRONT + "/runs/" + uiRun);
    await page.getByTestId("plan-card").waitFor();
    await page.getByTestId("run-result").waitFor();
    check("finished run replays from GET /api/runs/:id", (await page.getByTestId("hard-count").innerText()).includes("9/9"));
    await page.getByTestId("compare-slider").waitFor({ timeout: 15000 });
    check("replay still shows artifacts", true);
    await shot(page, "swarm-finished", "d");

    // ---- other task types via the API, viewed in the UI
    const repo = async (r, task, taskType) => (await post("/api/tasks", { repo: r, branch: "main", task, ...(taskType ? { taskType } : {}) })).runId;
    const settle = async (id) => {
      for (let i = 0; i < 120; i++) {
        const r = await get("/api/runs/" + id);
        if (r.completedAt) return r;
        await new Promise((x) => setTimeout(x, 500));
      }
      throw new Error("run did not finish " + id);
    };
    const feat = await repo("demo/shop-api", "Add bulk discount tiers");
    const ref = await repo("demo/wordstats", "Split the monolithic module, keep the public API");
    const part = await repo("demo/shop-api", "Write a migration guide for the new API", "docs");
    const bad = await repo("demo/shop-api", "This is unsolvable: make the tests pass by deleting them");
    const vague = await repo("demo/shop-api", "make it better");
    const [rf, rr, rp, rb, rv] = await Promise.all([feat, ref, part, bad, vague].map(settle));
    check("feature run: tests first, complete", rf.outcome === "complete" && rf.taskType === "feature" && rf.plan.criteria.some((c) => c.kind === "acceptance_tests"));
    check("refactor run: characterization + API surface, complete", rr.outcome === "complete" && rr.plan.criteria.some((c) => c.kind === "api_surface"));
    check("docs run is partial", rp.outcome === "partial");
    check("unsolvable run fails honestly, no PR", rb.outcome === "failed" && !rb.prUrl);
    check("vague run asks for input", rv.outcome === "needs_input");
    check("vague run is never declined as untestable", rv.status === "completed");
    await page.goto(FRONT + "/runs/" + feat);
    await page.getByTestId("run-result").waitFor();
    await shot(page, "swarm-feature", "d");
    await page.goto(FRONT + "/runs/" + part);
    await page.getByTestId("partial-warning").waitFor({ timeout: 15000 });
    check("partial run warns before merge", (await page.getByTestId("unverified").innerText()).includes("no executable verifier"));
    await shot(page, "swarm-partial", "d");
    await page.goto(FRONT + "/runs/" + bad);
    await page.getByTestId("run-result").waitFor();
    check("failed outcome shown, no PR card", (await page.getByTestId("run-result").getAttribute("data-outcome")) === "failed" && (await page.getByTestId("pr-card").count()) === 0);
    await shot(page, "swarm-failed", "d");

    // ---- needs_input path through the UI
    await page.goto(FRONT + "/runs/" + vague);
    await page.getByTestId("clarify-form").waitFor();
    check("send disabled until every question is answered", await page.getByTestId("answers-send").isDisabled());
    await shot(page, "needs-input", "d");
    await page.getByTestId("answer-q1").fill("The todo list page looks plain and breaks on phones.");
    await page.getByTestId("answer-q2").fill("Improve the UI so it looks better and is responsive.");
    await page.getByTestId("answers-send").click();
    await page.waitForURL((u) => /\/runs\//.test(u.pathname) && !u.pathname.endsWith(vague), { timeout: 10000 });
    await page.getByTestId("run-result").waitFor({ timeout: 60000 });
    check("answers re-run the task to completion", (await page.getByTestId("run-result").getAttribute("data-outcome")) === "complete");

    // ---- dashboard, bell, tokens
    await page.goto(FRONT + "/dashboard");
    await page.getByTestId("runs-table").waitFor();
    check("dashboard lists runs", (await page.locator("[data-testid=runs-table] tbody tr").count()) >= 8);
    const tbl = await page.getByTestId("runs-table").innerText();
    check("dashboard shows outcome chips, gates and agents", /Complete/.test(tbl) && /Partial/.test(tbl) && /Needs input/.test(tbl) && /gates/.test(tbl) && /peak/.test(tbl));
    await shot(page, "dashboard", "d");
    await page.goto(FRONT + "/settings/tokens");
    await page.getByTestId("token-name").fill("laptop");
    await page.getByTestId("token-create").click();
    await page.getByTestId("new-token").waitFor();
    check("API token created", true);
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
    for (const [name, url, wait] of [
      ["landing", "/", 6000],
      ["dashboard", "/dashboard", 1200],
      ["swarm-finished", "/runs/" + uiRun, 2500],
      ["swarm-feature", "/runs/" + feat, 1800],
      ["swarm-partial", "/runs/" + part, 1800],
      ["swarm-failed", "/runs/" + bad, 1500],
      ["needs-input", "/runs/" + vague, 1500],
      ["docs", "/docs/getting-started", 800],
    ]) {
      await mp.goto(FRONT + url);
      await mp.waitForTimeout(wait);
      await overflow(name);
      await shot(mp, name, "m");
    }
    await mp.goto(FRONT + "/new");
    await mp.locator('[data-repo="demo/react-todo"]').click();
    await mp.getByTestId("next").click();
    await mp.getByTestId("type-ui").check({ force: true });
    await overflow("new-2-types");
    await shot(mp, "new-2-task", "m");
    // live swarm at 375
    await mp.getByTestId("task-input").fill("Add bulk discount tiers");
    await mp.getByTestId("next").click();
    await mp.getByTestId("start-task").click();
    await mp.waitForURL(/\/runs\//);
    await mp.waitForSelector('[data-agent][data-status="running"]', { timeout: 30000 });
    await overflow("swarm-live");
    await shot(mp, "swarm-live", "m");
    await mp.goto(FRONT + "/runs/" + uiRun);
    await mp.getByTestId("compare-slider").waitFor({ timeout: 15000 });
    await mp.getByTestId("enlarge").click();
    await mp.getByTestId("lightbox").waitFor();
    await overflow("lightbox");
    await shot(mp, "lightbox", "m");
    check("no page errors (mobile)", merrors.length === 0, merrors.join(" | "));
    await m.close();

    // ---- reduced motion: no looping animation on the landing demo
    const rm = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    const rp2 = await rm.newPage();
    await rp2.goto(FRONT + "/");
    await rp2.getByTestId("live-demo").waitFor();
    await rp2.waitForSelector('[data-testid="live-demo"] [data-stage="pr"][data-state="done"]', { timeout: 5000 }).catch(() => {});
    check("reduced motion: landing demo renders its final frame", await rp2.locator('[data-testid="live-demo"] [data-stage="pr"][data-state="done"]').isVisible());
    await rm.close();
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
