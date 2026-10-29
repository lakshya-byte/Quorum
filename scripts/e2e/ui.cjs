#!/usr/bin/env node
// Browser e2e against the RUNNING local stack (scripts/dev-up.sh): sign up (OTP from the DEV_MODE
// endpoint), sign in, start a hard-bug run from the dashboard, wait for the finished tree on
// /runs/[id], then /try as a guest (mid-run and finished). Screenshots at 1440px and 390px.
//
//   node scripts/e2e/ui.cjs [screenshot-dir]
//
// Needs the `playwright` package with Chromium (not a repo dependency: install it globally or set
// NODE_PATH). Reads AGENT_SHARED_SECRET from .logs/dev.env. Uses 1 guest run (3/hour per IP).
const fs = require("fs");
const path = require("path");

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
const HARD_BUG = process.env.E2E_HARD_BUG || "version_sort";
const OUT = path.resolve(process.argv[2] || path.join(ROOT, ".logs", "screens-e2e"));
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, ok, detail = "") => {
  results.push([name, ok ? "PASS" : "FAIL", detail]);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  " + detail : ""}`);
};
const shots = [];
async function shot(page, name) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  shots.push(file);
}

async function devOtp(email) {
  for (let i = 0; i < 20; i++) {
    const r = await fetch(`${BACK}/internal/dev/otp?email=${encodeURIComponent(email)}`, {
      headers: { "X-Agent-Secret": SECRET },
    });
    if (r.ok) return (await r.json()).code;
    await new Promise((res) => setTimeout(res, 250));
  }
  throw new Error("no OTP for the new account (is DEV_MODE=true?)");
}

(async () => {
  if (!SECRET) throw new Error("AGENT_SHARED_SECRET unknown (run scripts/dev-up.sh)");
  const browser = await chromium.launch();
  const consoleErrors = [];
  const badResponses = []; // 401 on /api/auth/me|refresh while signed out is expected
  const FIXED = /Fixed: attempt #\d+ passes/;
  try {
    // ------------------------------------------------------------ signed-in flow, desktop
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    page.on("console", (m) => m.type() === "error" && !/status of 401/.test(m.text()) && consoleErrors.push(m.text()));
    page.on("response", (r) => r.status() >= 400 && badResponses.push(`${r.status()} ${new URL(r.url()).pathname}`));
    const email = `ui-${Date.now()}@example.com`;
    const password = "ui-e2e-password";

    await page.goto(`${FRONT}/signup`);
    await page.fill("#corporate-email", email);
    await page.fill("#org-name", "UI E2E Inc");
    await page.fill("#new-password", password);
    await page.click('[data-testid="signup-form"] button[type="submit"]');
    await page.waitForSelector("#otp-code", { timeout: 15000 });
    await page.fill("#otp-code", await devOtp(email));
    await page.click('[data-testid="otp-form"] button[type="submit"]');
    await page.waitForURL("**/dashboard", { timeout: 20000 });
    check("sign up + OTP verify lands on /dashboard", true);

    // Sign in again from a clean session.
    await ctx.clearCookies();
    await page.goto(`${FRONT}/signin`);
    await page.fill("#work-email", email);
    await page.fill("#password", password);
    await page.click('form button[type="submit"]');
    await page.waitForURL("**/dashboard", { timeout: 20000 });
    check("sign in lands on /dashboard", true);

    await page.waitForSelector(`[data-testid="bug-select"] option[value="${HARD_BUG}"]`, { state: "attached", timeout: 20000 });
    await page.selectOption('[data-testid="bug-select"]', HARD_BUG);
    await page.click('button[role="radio"]:has-text("Agent team")');
    await shot(page, "dashboard-1440");
    const t0 = Date.now();
    await page.click('[data-testid="new-fix"]');
    await page.waitForURL("**/runs/*", { timeout: 20000 });
    const runUrl = page.url();
    await page.waitForSelector('[data-testid="run-result"]', { timeout: 60000 });
    const resultText = (await page.textContent('[data-testid="run-result"]')) || "";
    const status = (await page.textContent('[data-testid="run-status"]')) || "";
    check("dashboard run on hard bug finishes solved on /runs/[id]", FIXED.test(resultText) && /Solved/.test(status),
      `${HARD_BUG} in ${Date.now() - t0} ms, "${resultText.replace(/\s+/g, " ").trim().slice(0, 80)}"`);
    const guardIn = (await page.textContent('[data-testid="guard-input"]').catch(() => "")) || "";
    check("input guard pill shows pass", /pass/i.test(guardIn), guardIn.replace(/\s+/g, " ").trim());
    const policy = (await page.textContent('[data-testid="guard-policy"]').catch(() => "")) || "";
    check("policy gate pill shows pass (summarised from node.policy)", /pass/i.test(policy), policy.replace(/\s+/g, " ").trim());
    await page.waitForTimeout(500);
    await shot(page, "run-finished-1440");

    // Reload: the saved run renders from the stored record.
    await page.reload();
    await page.waitForSelector('[data-testid="run-result"]', { timeout: 30000 });
    const reloaded = (await page.textContent('[data-testid="run-result"]')) || "";
    check("reloaded /runs/[id] (saved run) shows the same fix", FIXED.test(reloaded), reloaded.replace(/\s+/g, " ").trim().slice(0, 60));

    // Same run on a phone.
    const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    await mctx.addCookies(await ctx.cookies());
    const mpage = await mctx.newPage();
    await mpage.goto(runUrl);
    await mpage.waitForSelector('[data-testid="run-result"]', { timeout: 30000 });
    const overflow = await mpage.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check("/runs/[id] at 390px has no horizontal page scroll", overflow <= 1, `overflow ${overflow}px`);
    await shot(mpage, "run-finished-390");
    await mctx.close();
    await ctx.close();

    // ------------------------------------------------------------ guest /try (mid-run + finished)
    // One guest run (3/hour per IP); the 390px shots resize the same page.
    {
      const gctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      const g = await gctx.newPage();
      await g.goto(`${FRONT}/try`);
      await g.click(`[data-bug-id="${HARD_BUG}"]`);
      await g.click('[data-testid="start-run"]');
      // Mid-run: the first proposals are on screen and the run is not finished yet.
      await g.waitForFunction(() => {
        const s = document.querySelector('[data-testid="run-status"]')?.textContent || "";
        return document.body.innerText.includes("#1") && !s.includes("Finished");
      }, null, { timeout: 30000, polling: 50 }).then(
        () => check("/try guest run shows nodes mid-run", true),
        () => check("/try guest run shows nodes mid-run", false, "finished before a mid-run frame was seen"),
      );
      await shot(g, "try-midrun-1440");
      await g.setViewportSize({ width: 390, height: 844 });
      await shot(g, "try-midrun-390");
      await g.setViewportSize({ width: 1440, height: 900 });
      await g.waitForSelector('[data-testid="run-result"]', { timeout: 60000 });
      const gText = (await g.textContent('[data-testid="run-result"]')) || "";
      check("/try guest run finishes solved", FIXED.test(gText), gText.replace(/\s+/g, " ").trim().slice(0, 60));
      await g.waitForTimeout(400);
      await shot(g, "try-finished-1440");
      await g.setViewportSize({ width: 390, height: 844 });
      await g.waitForTimeout(300);
      const gOverflow = await g.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check("/try at 390px has no horizontal page scroll", gOverflow <= 1, `overflow ${gOverflow}px`);
      await shot(g, "try-finished-390");
      await gctx.close();
    }
  } catch (err) {
    check("browser flow", false, String(err && err.message ? err.message : err).split("\n")[0]);
  } finally {
    await browser.close();
  }
  const relevant = consoleErrors.filter((t) => !/favicon|Download the React DevTools/i.test(t));
  const unexpected = badResponses.filter((r) => !/^401 \/api\/auth\/(me|refresh)$/.test(r));
  check("no unexpected HTTP errors", unexpected.length === 0, `${unexpected.slice(0, 4).join(", ")} (expected while signed out: ${badResponses.length - unexpected.length}x 401 auth/me|refresh)`);
  check("no browser console errors (besides those 401s)", relevant.length === 0, relevant.slice(0, 2).join(" | ").slice(0, 200));
  console.log(`\nscreenshots (${shots.length}):\n  ${shots.join("\n  ")}`);
  const fails = results.filter((r) => r[1] === "FAIL").length;
  console.log(`${results.length - fails} PASS, ${fails} FAIL`);
  process.exit(fails ? 1 : 0);
})();
