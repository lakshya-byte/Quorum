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

const INVENTORY = {
  "inventory/stock.py": `class OutOfStock(Exception):
    pass


class Stock:
    def __init__(self, items=None):
        self.items = dict(items or {})
        self.reserved = {}

    def available(self, sku):
        return self.items.get(sku, 0) - self.reserved.get(sku, 0)

    def reserve(self, sku, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        if qty >= self.available(sku):
            raise OutOfStock(sku)
        self.reserved[sku] = self.reserved.get(sku, 0) + qty

    def release(self, sku, qty):
        self.reserved[sku] = self.reserved.get(sku, 0) - qty
`,
  "inventory/api.py": `from .stock import OutOfStock, Stock

stock = Stock({"widget": 5, "gadget": 1})


def reserve_endpoint(sku, qty):
    try:
        stock.reserve(sku, qty)
    except OutOfStock:
        return {"status": 409, "error": "out of stock"}
    return {"status": 200, "available": stock.available(sku)}


def release_endpoint(sku, qty):
    stock.release(sku, qty)
    return {"status": 200, "available": stock.available(sku)}
`,
  "tests/test_stock.py": `import unittest
from inventory.stock import Stock, OutOfStock


class StockTest(unittest.TestCase):
    def test_reserve_last_unit(self):
        s = Stock({"a": 1})
        s.reserve("a", 1)
        self.assertEqual(s.available("a"), 0)

    def test_over_reserve_raises(self):
        s = Stock({"a": 1})
        with self.assertRaises(OutOfStock):
            s.reserve("a", 2)

    def test_release_never_negative(self):
        s = Stock({"a": 3})
        s.reserve("a", 1)
        s.release("a", 5)
        self.assertEqual(s.reserved["a"], 0)
`,
};

const BILLING = {
  "billing/invoice.py": `TAX_RATE = 0.2


def total_with_tax(subtotal):
    """Return the invoice total including tax, rounded to cents."""
    return round(subtotal * (1 + TAX_RATE))


def split_evenly(total, parts):
    base = round(total / parts, 2)
    return [base] * parts
`,
  "tests/test_invoice.py": `import unittest
from billing.invoice import total_with_tax, split_evenly


class InvoiceTest(unittest.TestCase):
    def test_total_keeps_cents(self):
        self.assertEqual(total_with_tax(10.00), 12.00)
        self.assertEqual(total_with_tax(19.99), 23.99)

    def test_split(self):
        self.assertEqual(split_evenly(9.0, 3), [3.0, 3.0, 3.0])
`,
};

const TEXT = {
  "texttools/words.py": `def word_count(text):
    """Count words separated by any amount of whitespace."""
    return len([w for w in text.split(" ")])


def longest_word(text):
    words = text.split()
    return max(words, key=len) if words else ""
`,
  "tests/test_words.py": `import unittest
from texttools.words import word_count, longest_word


class WordsTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(word_count("hello world"), 2)

    def test_multiple_spaces(self):
        self.assertEqual(word_count("hello   world"), 2)

    def test_empty(self):
        self.assertEqual(word_count(""), 0)

    def test_longest(self):
        self.assertEqual(longest_word("a abc ab"), "abc")
`,
};

function patch(files, edits) {
  const out = { ...files };
  for (const [p, from, to] of edits) out[p] = out[p].replace(from, to);
  return out;
}

export const DEMO_REPOS = [
  {
    fullName: "demo/inventory-api",
    description: "Tiny stock-reservation service (demo repository, Python)",
    language: "Python",
    total: 3,
    files: INVENTORY,
    locate: [
      { path: "inventory/stock.py", reason: "reserve() compares against available() with >=" },
      { path: "inventory/api.py", reason: "release_endpoint passes through to Stock.release" },
    ],
    repro: { path: "tests/test_stock.py", test_name: "test_reserve_last_unit", failing: 1 },
    cause: "Stock.reserve rejects a reservation equal to the remaining units (>= instead of >), and release() can push the reserved count below zero.",
    strategies: ["Fix the off-by-one comparison in reserve()", "Clamp release() at zero as well", "Rewrite reserve() around a single available() check"],
    candidates: [
      { id: 1, parent: 0, label: "wrong", idea: "Flip the comparison in reserve() only", edits: [["inventory/stock.py", "qty >= self.available(sku)", "qty > self.available(sku) + 1"]], failing: 1 },
      { id: 2, parent: 0, label: "partial", idea: "Fix the off-by-one in reserve()", edits: [["inventory/stock.py", "qty >= self.available(sku)", "qty > self.available(sku)"]], failing: 1 },
      { id: 3, parent: 0, label: "policy", idea: "Patch and add a CI workflow that deploys", edits: [["inventory/stock.py", "qty >= self.available(sku)", "qty > self.available(sku)"]], blocked: ["Touches .github/: workflows are off limits"] },
      {
        id: 4,
        parent: 2,
        label: "fix",
        idea: "Fix reserve() and clamp release() at zero",
        edits: [
          ["inventory/stock.py", "qty >= self.available(sku)", "qty > self.available(sku)"],
          ["inventory/stock.py", "self.reserved[sku] = self.reserved.get(sku, 0) - qty", "self.reserved[sku] = max(0, self.reserved.get(sku, 0) - qty)"],
          ["inventory/api.py", "    stock.release(sku, qty)\n    return", "    stock.release(sku, qty)\n    # release is idempotent: never reports a negative reservation\n    return"],
        ],
        failing: 0,
      },
      { id: 5, parent: 2, label: "security", idea: "Evaluate the quantity expression dynamically", edits: [["inventory/stock.py", "qty >= self.available(sku)", "eval('qty > self.available(sku)')"]], failing: 0, security: true },
    ],
    winner: 4,
  },
  {
    fullName: "demo/billing-utils",
    description: "Invoice totals and splitting helpers (demo repository, Python)",
    language: "Python",
    total: 2,
    files: BILLING,
    locate: [{ path: "billing/invoice.py", reason: "total_with_tax rounds to a whole number" }],
    repro: { path: "tests/test_invoice.py", test_name: "test_total_keeps_cents", failing: 1 },
    cause: "total_with_tax calls round() without a precision argument, so cents are dropped: 19.99 becomes 24 instead of 23.99.",
    strategies: ["Round to 2 decimals", "Use Decimal for money maths", "Multiply by 100, round, divide"],
    candidates: [
      { id: 1, parent: 0, label: "wrong", idea: "Round to 1 decimal", edits: [["billing/invoice.py", "(1 + TAX_RATE))", "(1 + TAX_RATE), 1)"]], failing: 1 },
      { id: 2, parent: 0, label: "fix", idea: "Round to 2 decimals", edits: [["billing/invoice.py", "(1 + TAX_RATE))", "(1 + TAX_RATE), 2)"]], failing: 0 },
      { id: 3, parent: 0, label: "policy", idea: "Shell out to bc for rounding", edits: [["billing/invoice.py", "round(subtotal", "__import__('os').system('bc') or round(subtotal"]], blocked: ["Disallowed side effect: shell access in patch"] },
    ],
    winner: 2,
  },
  {
    fullName: "demo/text-tools",
    description: "Small text helpers (demo repository, Python)",
    language: "Python",
    total: 4,
    files: TEXT,
    locate: [{ path: "texttools/words.py", reason: "word_count splits on a single space" }],
    repro: { path: "tests/test_words.py", test_name: "test_multiple_spaces", failing: 2 },
    cause: "word_count uses text.split(\" \"), which yields empty strings for repeated spaces and for the empty string.",
    strategies: ["Use str.split() with no argument", "Filter empty strings after splitting", "Count with a regular expression"],
    candidates: [
      { id: 1, parent: 0, label: "partial", idea: "Filter empty strings after splitting", edits: [["texttools/words.py", "return len([w for w in text.split(\" \")])", "return len([w for w in text.split(\" \") if w])"]], failing: 0 },
      { id: 2, parent: 0, label: "fix", idea: "Use str.split() without arguments", edits: [["texttools/words.py", "return len([w for w in text.split(\" \")])", "return len(text.split())"]], failing: 0 },
      { id: 3, parent: 0, label: "wrong", idea: "Count spaces plus one", edits: [["texttools/words.py", "return len([w for w in text.split(\" \")])", "return text.count(\" \") + 1"]], failing: 2 },
    ],
    winner: 2,
  },
];

export function repoByName(name) {
  return DEMO_REPOS.find((r) => r.fullName === name);
}

export function candidateFiles(repo, c) {
  return patch(repo.files, c.edits);
}

export function candidateDiff(repo, c) {
  const after = candidateFiles(repo, c);
  return Object.keys(after)
    .filter((p) => after[p] !== repo.files[p])
    .map((p) => unifiedDiff(p, repo.files[p], after[p]))
    .join("");
}
