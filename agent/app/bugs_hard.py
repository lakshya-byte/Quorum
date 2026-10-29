"""Hard bugs: vague user-style reports, 2-3 layered defects, the exact rules live only in the tests.

Same shape as app/bugs.py (buggy / tests / wrong / partial / correct). Target: one Nemotron-Nano
attempt solves 20-70% of these (pending live calibration, see evals/README.md).
"""
from __future__ import annotations

Bug = dict[str, str]

MONEY_TOTAL: Bug = {
    "id": "money_total",
    "tier": "hard",
    "title": "Invoice totals are off by a cent and coupons look wrong",
    "issue": (
        "Customers say invoice totals are sometimes off by a cent. When they use a coupon the total "
        "looks too high, and one customer whose coupon was bigger than the order got a negative total. "
        "Finance says totals must be exact money amounts, not floats."
    ),
    "target": "invoice.py",
    "buggy": '''def invoice_total(lines, coupon="0", tax_rate="0"):
    """Total for (unit_price, qty) lines after a money coupon and a tax rate."""
    subtotal = sum(float(price) * qty for price, qty in lines)
    total = subtotal * (1 + float(tax_rate)) - float(coupon)
    return round(total, 2)
''',
    "tests": '''import unittest
from decimal import Decimal

from invoice import invoice_total


class TestInvoiceTotal(unittest.TestCase):
    def test_simple_total(self):
        self.assertEqual(invoice_total([("10.00", 2), ("5.00", 1)]), Decimal("25.00"))

    def test_returns_exact_decimal(self):
        result = invoice_total([("10.00", 1)])
        self.assertIsInstance(result, Decimal)
        self.assertEqual(result.as_tuple().exponent, -2)

    def test_coupon_is_applied_before_tax(self):
        self.assertEqual(invoice_total([("100.00", 1)], coupon="10", tax_rate="0.10"), Decimal("99.00"))

    def test_rounds_half_up(self):
        self.assertEqual(invoice_total([("0.125", 1)]), Decimal("0.13"))

    def test_rounds_half_up_after_tax(self):
        self.assertEqual(invoice_total([("2.10", 1)], tax_rate="0.05"), Decimal("2.21"))

    def test_coupon_larger_than_order_is_zero(self):
        self.assertEqual(invoice_total([("5.00", 1)], coupon="8", tax_rate="0.10"), Decimal("0.00"))

    def test_no_float_error(self):
        self.assertEqual(invoice_total([("0.10", 3)]), Decimal("0.30"))


if __name__ == "__main__":
    unittest.main()
''',
    "wrong": '''from decimal import Decimal, ROUND_HALF_UP


def invoice_total(lines, coupon="0", tax_rate="0"):
    """Total for (unit_price, qty) lines after a money coupon and a tax rate."""
    subtotal = sum(Decimal(price) * qty for price, qty in lines)
    total = subtotal * (1 + Decimal(tax_rate)) - Decimal(coupon)
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
''',
    "partial": '''from decimal import Decimal


def invoice_total(lines, coupon="0", tax_rate="0"):
    """Total for (unit_price, qty) lines after a money coupon and a tax rate."""
    subtotal = sum(Decimal(price) * qty for price, qty in lines)
    total = (subtotal - Decimal(coupon)) * (1 + Decimal(tax_rate))
    return total.quantize(Decimal("0.01"))
''',
    "correct": '''from decimal import Decimal, ROUND_HALF_UP


def invoice_total(lines, coupon="0", tax_rate="0"):
    """Total for (unit_price, qty) lines after a money coupon and a tax rate."""
    subtotal = sum((Decimal(price) * qty for price, qty in lines), Decimal("0"))
    discounted = max(subtotal - Decimal(coupon), Decimal("0"))
    total = discounted * (1 + Decimal(tax_rate))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
''',
}

VERSION_SORT: Bug = {
    "id": "version_sort",
    "tier": "hard",
    "title": "Release page lists versions in a weird order",
    "issue": (
        "Our releases page shows versions in a strange order: 1.10 appears before 1.9, and release "
        "candidates show up after the real release. Some tags are written with a 'v' in front and "
        "those end up in the wrong place too. Please keep the tags exactly as they were written."
    ),
    "target": "versions.py",
    "buggy": '''def sort_versions(versions):
    """Return the version strings sorted from oldest to newest."""
    return sorted(versions)
''',
    "tests": '''import unittest

from versions import sort_versions


class TestSortVersions(unittest.TestCase):
    def test_numeric_components(self):
        self.assertEqual(sort_versions(["1.10.0", "1.9.0", "1.2.0"]), ["1.2.0", "1.9.0", "1.10.0"])

    def test_already_sorted(self):
        self.assertEqual(sort_versions(["0.1", "0.2", "0.3"]), ["0.1", "0.2", "0.3"])

    def test_leading_v_is_ignored_but_kept(self):
        self.assertEqual(sort_versions(["1.10.0", "v1.2.0"]), ["v1.2.0", "1.10.0"])

    def test_prerelease_before_release(self):
        self.assertEqual(sort_versions(["1.0.0", "1.0.0-rc1", "0.9.0"]), ["0.9.0", "1.0.0-rc1", "1.0.0"])

    def test_prereleases_ordered_by_label(self):
        self.assertEqual(sort_versions(["1.0.0-beta", "1.0.0-alpha"]), ["1.0.0-alpha", "1.0.0-beta"])

    def test_does_not_mutate_input(self):
        data = ["2.0", "1.0"]
        sort_versions(data)
        self.assertEqual(data, ["2.0", "1.0"])

    def test_missing_components(self):
        self.assertEqual(sort_versions(["1.0.1", "1"]), ["1", "1.0.1"])


if __name__ == "__main__":
    unittest.main()
''',
    "wrong": '''def sort_versions(versions):
    """Return the version strings sorted from oldest to newest."""
    return sorted(versions, key=lambda v: [int(p) for p in v.split(".")])
''',
    "partial": '''def sort_versions(versions):
    """Return the version strings sorted from oldest to newest."""
    def key(v):
        core = v.lstrip("vV").split("-")[0]
        return [int(p) for p in core.split(".")]
    return sorted(versions, key=key)
''',
    "correct": '''def sort_versions(versions):
    """Return the version strings sorted from oldest to newest."""
    def key(v):
        text = v[1:] if v[:1] in ("v", "V") else v
        core, _, pre = text.partition("-")
        nums = [int(p) for p in core.split(".")]
        while nums and nums[-1] == 0:
            nums.pop()
        return (nums, 0 if pre else 1, pre)
    return sorted(versions, key=key)
''',
}

MERGE_INTERVALS: Bug = {
    "id": "merge_intervals",
    "tier": "hard",
    "title": "Busy-time merge is flaky and corrupts the meeting list",
    "issue": (
        "The calendar's busy-time view is flaky. Back-to-back meetings show up as separate blocks, "
        "the result depends on the order meetings were added, and after the merge runs the original "
        "meeting list has been changed."
    ),
    "target": "intervals.py",
    "buggy": '''def merge_intervals(intervals):
    """Merge [start, end] intervals into a sorted list of non-overlapping intervals."""
    merged = []
    for interval in intervals:
        if merged and interval[0] < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], interval[1])
        else:
            merged.append(interval)
    return merged
''',
    "tests": '''import copy
import unittest

from intervals import merge_intervals


class TestMergeIntervals(unittest.TestCase):
    def test_overlapping(self):
        self.assertEqual(merge_intervals([[1, 3], [2, 6], [8, 10]]), [[1, 6], [8, 10]])

    def test_disjoint(self):
        self.assertEqual(merge_intervals([[1, 2], [5, 6]]), [[1, 2], [5, 6]])

    def test_adjacent_intervals_merge(self):
        self.assertEqual(merge_intervals([[1, 2], [2, 3]]), [[1, 3]])

    def test_unsorted_input(self):
        self.assertEqual(merge_intervals([[8, 10], [1, 3], [2, 6]]), [[1, 6], [8, 10]])

    def test_input_is_not_mutated(self):
        data = [[1, 3], [2, 4]]
        before = copy.deepcopy(data)
        merge_intervals(data)
        self.assertEqual(data, before)

    def test_empty(self):
        self.assertEqual(merge_intervals([]), [])

    def test_contained_interval(self):
        self.assertEqual(merge_intervals([[1, 10], [2, 3]]), [[1, 10]])


if __name__ == "__main__":
    unittest.main()
''',
    "wrong": '''def merge_intervals(intervals):
    """Merge [start, end] intervals into a sorted list of non-overlapping intervals."""
    merged = []
    for interval in sorted(intervals):
        if merged and interval[0] < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], interval[1])
        else:
            merged.append(interval)
    return merged
''',
    "partial": '''def merge_intervals(intervals):
    """Merge [start, end] intervals into a sorted list of non-overlapping intervals."""
    merged = []
    for interval in sorted(intervals):
        if merged and interval[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], interval[1])
        else:
            merged.append(interval)
    return merged
''',
    "correct": '''def merge_intervals(intervals):
    """Merge [start, end] intervals into a sorted list of non-overlapping intervals."""
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
''',
}

LRU_CACHE: Bug = {
    "id": "lru_cache",
    "tier": "hard",
    "title": "Cache evicts things we just used and crashes at size 0",
    "issue": (
        "Our in-memory cache keeps evicting entries we just read. Updating a key that is already "
        "cached sometimes kicks out a different entry, and a worker configured with a cache size of 0 "
        "crashes on the first write."
    ),
    "target": "lru.py",
    "buggy": '''class LRUCache:
    """Least-recently-used cache with a fixed capacity."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def put(self, key, value):
        if len(self.data) >= self.capacity:
            oldest = next(iter(self.data))
            del self.data[oldest]
        self.data[key] = value

    def __len__(self):
        return len(self.data)
''',
    "tests": '''import unittest

from lru import LRUCache


class TestLRUCache(unittest.TestCase):
    def test_put_and_get(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        self.assertEqual(cache.get("a"), 1)

    def test_missing_key_returns_default(self):
        self.assertEqual(LRUCache(2).get("x", "d"), "d")

    def test_evicts_oldest(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        self.assertIsNone(cache.get("a"))
        self.assertEqual((cache.get("b"), cache.get("c")), (2, 3))

    def test_get_refreshes_recency(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")
        cache.put("c", 3)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), 1)

    def test_update_does_not_evict_others(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("b", 20)
        self.assertEqual((cache.get("a"), cache.get("b")), (1, 20))

    def test_update_refreshes_recency(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("a", 10)
        cache.put("c", 3)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), 10)

    def test_capacity_zero_stores_nothing(self):
        cache = LRUCache(0)
        cache.put("a", 1)
        self.assertEqual(len(cache), 0)
        self.assertIsNone(cache.get("a"))

    def test_len(self):
        cache = LRUCache(3)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(len(cache), 2)


if __name__ == "__main__":
    unittest.main()
''',
    "wrong": '''from collections import OrderedDict


class LRUCache:
    """Least-recently-used cache with a fixed capacity."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key, default=None):
        return self.data.get(key, default)

    def put(self, key, value):
        if key in self.data:
            self.data.move_to_end(key)
        elif len(self.data) >= self.capacity:
            self.data.popitem(last=False)
        self.data[key] = value

    def __len__(self):
        return len(self.data)
''',
    "partial": '''from collections import OrderedDict


class LRUCache:
    """Least-recently-used cache with a fixed capacity."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key, default=None):
        if key not in self.data:
            return default
        self.data.move_to_end(key)
        return self.data[key]

    def put(self, key, value):
        if key in self.data:
            self.data.move_to_end(key)
        elif len(self.data) >= self.capacity:
            self.data.popitem(last=False)
        self.data[key] = value

    def __len__(self):
        return len(self.data)
''',
    "correct": '''from collections import OrderedDict


class LRUCache:
    """Least-recently-used cache with a fixed capacity."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key, default=None):
        if key not in self.data:
            return default
        self.data.move_to_end(key)
        return self.data[key]

    def put(self, key, value):
        if self.capacity <= 0:
            return
        if key in self.data:
            self.data.move_to_end(key)
        elif len(self.data) >= self.capacity:
            self.data.popitem(last=False)
        self.data[key] = value

    def __len__(self):
        return len(self.data)
''',
}

SLUGIFY_UNICODE: Bug = {
    "id": "slugify_unicode",
    "tier": "hard",
    "title": "Recipe URLs look broken for accented and long titles",
    "issue": (
        "URLs for our French recipes look broken: 'Crème Brûlée' turns into a mess of dashes. Titles "
        "with extra spaces or punctuation get double dashes or dashes at the ends, and long titles "
        "sometimes end with a dash after they are shortened."
    ),
    "target": "slug_unicode.py",
    "buggy": '''import re


def slugify(text, max_length=40):
    """Turn a title into a URL slug of at most max_length characters."""
    slug = re.sub(r"[^a-z0-9]", "-", text.lower())
    return slug[:max_length]
''',
    "tests": '''import unittest

from slug_unicode import slugify


class TestSlugifyUnicode(unittest.TestCase):
    def test_plain_words(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_accents_are_transliterated(self):
        self.assertEqual(slugify("Crème Brûlée"), "creme-brulee")

    def test_separators_collapse(self):
        self.assertEqual(slugify("a  --  b"), "a-b")

    def test_no_dash_at_the_ends(self):
        self.assertEqual(slugify("  Hello!  "), "hello")

    def test_max_length(self):
        self.assertEqual(slugify("a" * 50), "a" * 40)

    def test_no_trailing_dash_after_cut(self):
        self.assertEqual(slugify("word " * 10), "-".join(["word"] * 8))

    def test_empty(self):
        self.assertEqual(slugify(""), "")

    def test_digits_kept(self):
        self.assertEqual(slugify("Python 3.12 Release"), "python-3-12-release")


if __name__ == "__main__":
    unittest.main()
''',
    "wrong": '''import re
import unicodedata


def slugify(text, max_length=40):
    """Turn a title into a URL slug of at most max_length characters."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]", "-", text.lower()).strip("-")
    return slug[:max_length]
''',
    "partial": '''import re


def slugify(text, max_length=40):
    """Turn a title into a URL slug of at most max_length characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length]
''',
    "correct": '''import re
import unicodedata


def slugify(text, max_length=40):
    """Turn a title into a URL slug of at most max_length characters."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length].rstrip("-")
''',
}

HARD_BUGS: tuple[Bug, ...] = (MONEY_TOTAL, VERSION_SORT, MERGE_INTERVALS, LRU_CACHE, SLUGIFY_UNICODE)
