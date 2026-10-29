import type { RunNode } from "../../_lib/api";
import type { StreamMessage } from "../../_lib/runState";

// A scripted replay of a demo run, fed through the same reducer the live run page uses.
// Content is illustrative: it mirrors the bundled demo repository "demo/inventory-api".

const STOCK_BEFORE = `    def reserve(self, sku, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        if qty >= self.available(sku):
            raise OutOfStock(sku)`;

export const DEMO_DIFF = `diff --git a/inventory/stock.py b/inventory/stock.py
--- a/inventory/stock.py
+++ b/inventory/stock.py
@@ -11,10 +11,10 @@
     def reserve(self, sku, qty):
         if qty <= 0:
             raise ValueError("qty must be positive")
-        if qty >= self.available(sku):
+        if qty > self.available(sku):
             raise OutOfStock(sku)
         self.reserved[sku] = self.reserved.get(sku, 0) + qty

     def release(self, sku, qty):
-        self.reserved[sku] = self.reserved.get(sku, 0) - qty
+        self.reserved[sku] = max(0, self.reserved.get(sku, 0) - qty)
diff --git a/inventory/api.py b/inventory/api.py
--- a/inventory/api.py
+++ b/inventory/api.py
@@ -13,4 +13,5 @@
 def release_endpoint(sku, qty):
     stock.release(sku, qty)
+    # release is idempotent: never reports a negative reservation
     return {"status": 200, "available": stock.available(sku)}
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

void STOCK_BEFORE;

export const DEMO_EVENTS: { at: number; msg: StreamMessage }[] = [
  { at: 300, msg: { type: "run_started", data: { mode: "fake", engine: "graph" } } },
  { at: 700, msg: { type: "repo", data: { full_name: "demo/inventory-api", branch: "main", files: 3, language: "Python", test_command: "python -m unittest" } } },
  { at: 1250, msg: { type: "locate", data: { files: [{ path: "inventory/stock.py" }, { path: "inventory/api.py" }] } } },
  { at: 1900, msg: { type: "repro", data: { path: "tests/test_stock.py", test_name: "test_reserve_last_unit", failed_on_original: true } } },
  { at: 2300, msg: { type: "node", data: n({ id: 0, parent: null, depth: 0, idea: "Original code", passed: 2, total: 3, model: null, tokens: 0 }) } },
  { at: 2600, msg: { type: "round", data: { depth: 1 } } },
  { at: 3300, msg: { type: "node", data: n({ id: 1, parent: 0, depth: 1, idea: "Flip the comparison in reserve() only", strategy: "off-by-one", passed: 2 }) } },
  { at: 3800, msg: { type: "node", data: n({ id: 2, parent: 0, depth: 1, idea: "Fix reserve(), keep the rest", strategy: "core fix", passed: 2 }) } },
  { at: 4200, msg: { type: "node", data: n({ id: 3, parent: 0, depth: 1, idea: "Patch and add a deploy workflow", strategy: "rewrite", passed: 0, policy: { ok: false, reasons: ["Touches .github/"] } }) } },
  { at: 4700, msg: { type: "critic", data: { node_id: 2, lesson: "Reserve is fixed but release() can still go negative. Extend this patch." } } },
  { at: 5300, msg: { type: "round", data: { depth: 2 } } },
  {
    at: 6300,
    msg: {
      type: "node",
      data: n({ id: 4, parent: 2, depth: 2, idea: "Fix reserve() and clamp release() at zero", strategy: "two-file fix", passed: 3, model: "nemotron-super", files: { "inventory/stock.py": "", "inventory/api.py": "" }, diff: DEMO_DIFF }),
    },
  },
  { at: 6800, msg: { type: "critic", data: { node_id: 4, lesson: "Reproducer and the existing suite both pass with a clean security scan." } } },
  { at: 7300, msg: { type: "guard", data: { stage: "output", verdict: "pass" } } },
  { at: 7600, msg: { type: "done", data: { solved: true, best: 4, usage: { prompt_tokens: 4200, completion_tokens: 1100 }, latency_ms: 7600 } } },
  { at: 8300, msg: { type: "pr", data: { url: "https://github.com/demo/inventory-api/pull/42", branch: "patchloop/reserve-last-unit", number: 42, fake: true } } },
  { at: 8350, msg: { type: "end", data: {} } },
];

export const DEMO_TOTAL_MS = 8400;
