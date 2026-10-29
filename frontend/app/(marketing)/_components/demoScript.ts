import type { RunNode } from "../../_lib/api";
import type { StreamMessage } from "../../_lib/runState";

// A scripted replay of a demo run, fed through the same reducer the live run page uses.
// The scenario is the bundled demo repository "demo/shop-api" (coupon + shipping bug). Timings and
// candidate ideas are scripted for the landing page; a real run streams the same event types.

export const DEMO_DIFF = `diff --git a/shop/coupons.py b/shop/coupons.py
--- a/shop/coupons.py
+++ b/shop/coupons.py
@@ -5,4 +5,4 @@
     """Return the discount in cents for \`percent\` off \`amount_cents\`, rounded half up."""
     if not 0 <= percent <= 100:
         raise ValueError("percent must be between 0 and 100")
-    return amount_cents * percent // 100
+    return (amount_cents * percent + 50) // 100
diff --git a/shop/cart.py b/shop/cart.py
--- a/shop/cart.py
+++ b/shop/cart.py
@@ -23,5 +23,5 @@
 
     def total(self):
         """Items minus the coupon, plus shipping. The coupon never discounts shipping."""
-        gross = self.subtotal() + self.shipping()
-        return gross - apply_percent(gross, self.coupon_percent)
+        items = self.subtotal()
+        return items - apply_percent(items, self.coupon_percent) + self.shipping()
`;

const n = (o: Partial<RunNode> & { id: number; parent: number | null; depth: number }): RunNode => ({
  passed: 0,
  total: 3,
  model: "nemotron-nano",
  latency_ms: 2400,
  tokens: 1300,
  policy: { ok: true },
  security: { ok: true },
  ...o,
});

export const DEMO_EVENTS: { at: number; msg: StreamMessage }[] = [
  { at: 300, msg: { type: "run_started", data: { mode: "fake", engine: "graph" } } },
  { at: 700, msg: { type: "repo", data: { full_name: "demo/shop-api", branch: "main", files: 7, language: "python", test_command: "python -m unittest discover" } } },
  { at: 1250, msg: { type: "locate", data: { files: [{ path: "shop/cart.py" }, { path: "shop/coupons.py" }] } } },
  { at: 1900, msg: { type: "repro", data: { path: "tests/test_patchloop_repro.py", test_name: "test_coupon_total_rounds_the_discount_and_keeps_shipping_full_price", failed_on_original: true } } },
  { at: 2300, msg: { type: "node", data: n({ id: 0, parent: null, depth: 0, idea: "Original code", passed: 2, total: 3, model: null, tokens: 0 }) } },
  { at: 2600, msg: { type: "round", data: { depth: 1 } } },
  { at: 3300, msg: { type: "node", data: n({ id: 1, parent: 0, depth: 1, idea: "Round the discount half up in coupons.py only", strategy: "off-by-one", passed: 2 }) } },
  { at: 3800, msg: { type: "node", data: n({ id: 2, parent: 0, depth: 1, idea: "Fix rounding, keep the cart as is", strategy: "core fix", passed: 2 }) } },
  { at: 4200, msg: { type: "node", data: n({ id: 3, parent: 0, depth: 1, idea: "Patch and add a CI workflow that deploys", strategy: "rewrite", passed: 0, policy: { ok: false, reasons: ["Touches .github/"] } }) } },
  { at: 4700, msg: { type: "critic", data: { node_id: 2, lesson: "Rounding is fixed but the coupon still discounts shipping. Extend this patch." } } },
  { at: 5300, msg: { type: "round", data: { depth: 2 } } },
  {
    at: 6300,
    msg: {
      type: "node",
      data: n({ id: 4, parent: 2, depth: 2, idea: "Round half up and keep shipping out of the discount", strategy: "two-file fix", passed: 3, model: "nemotron-super", files: { "shop/coupons.py": "", "shop/cart.py": "" }, diff: DEMO_DIFF }),
    },
  },
  { at: 6800, msg: { type: "critic", data: { node_id: 4, lesson: "Reproducer and the existing suite both pass with a clean security scan." } } },
  { at: 7300, msg: { type: "guard", data: { stage: "output", verdict: "pass" } } },
  { at: 7600, msg: { type: "done", data: { solved: true, best: 4, usage: { prompt_tokens: 4200, completion_tokens: 1100 }, latency_ms: 7600 } } },
  { at: 8300, msg: { type: "pr", data: { url: "https://github.com/demo/shop-api/pull/42", branch: "patchloop/fix-coupon-totals", number: 42, fake: true } } },
  { at: 8350, msg: { type: "end", data: {} } },
];

export const DEMO_TOTAL_MS = 8400;
