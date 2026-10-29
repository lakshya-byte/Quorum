"""Four demo bugs. Each has a buggy source, unittest tests and scripted fixes for fake mode.

`partial` is the obvious first fix: it passes most tests but misses an edge case,
so a search has to go one level deeper to find `correct`.
"""
from __future__ import annotations

Bug = dict[str, str]


PAGINATE: Bug = {
    "id": "paginate",
    "tier": "easy",
    "title": "paginate() skips the first page",
    "issue": (
        "paginate(items, page, per_page) should return the items on a 1-indexed page: "
        "page 1 is the first page. Right now page 1 returns the second page of results. "
        "A page number below 1 is a caller error and must raise ValueError."
    ),
    "target": "pagination.py",
    "buggy": '''def paginate(items, page, per_page):
    """Return the items on the given 1-indexed page."""
    start = page * per_page
    return items[start:start + per_page]
''',
    "tests": '''import unittest

from pagination import paginate

ITEMS = list(range(1, 11))


class TestPaginate(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(paginate(ITEMS, 1, 3), [1, 2, 3])

    def test_second_page(self):
        self.assertEqual(paginate(ITEMS, 2, 3), [4, 5, 6])

    def test_last_partial_page(self):
        self.assertEqual(paginate(ITEMS, 4, 3), [10])

    def test_page_past_the_end_is_empty(self):
        self.assertEqual(paginate(ITEMS, 5, 3), [])

    def test_page_zero_raises(self):
        with self.assertRaises(ValueError):
            paginate(ITEMS, 0, 3)

    def test_negative_page_raises(self):
        with self.assertRaises(ValueError):
            paginate(ITEMS, -1, 3)


if __name__ == "__main__":
    unittest.main()
''',
    "wrong": '''def paginate(items, page, per_page):
    """Return the items on the given 1-indexed page."""
    start = page * per_page - 1
    return items[start:start + per_page]
''',
    "partial": '''def paginate(items, page, per_page):
    """Return the items on the given 1-indexed page."""
    start = (page - 1) * per_page
    return items[start:start + per_page]
''',
    "correct": '''def paginate(items, page, per_page):
    """Return the items on the given 1-indexed page."""
    if page < 1:
        raise ValueError("page must be >= 1")
    start = (page - 1) * per_page
    return items[start:start + per_page]
''',
}


SLUGIFY: Bug = {
    "id": "slugify",
    "tier": "easy",
    "title": "slugify() keeps punctuation and stray dashes",
    "issue": (
        "slugify(text) should produce a URL slug: lowercase, punctuation dropped, words "
        "joined by single dashes, no leading or trailing dash. 'C++ & Python!' must become "
        "'c-python' and '' must stay ''. Passing something that is not a string must raise TypeError."
    ),
    "target": "slug.py",
    "buggy": '''def slugify(text):
    """Turn a title into a URL slug."""
    return text.lower().replace(" ", "-")
''',
    "tests": '''import unittest

from slug import slugify


class TestSlugify(unittest.TestCase):
    def test_simple_words(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_punctuation_is_dropped(self):
        self.assertEqual(slugify("C++ & Python!"), "c-python")

    def test_repeated_spaces_collapse(self):
        self.assertEqual(slugify("a   b"), "a-b")

    def test_no_leading_or_trailing_dash(self):
        self.assertEqual(slugify("  Hello, World  "), "hello-world")

    def test_empty_string(self):
        self.assertEqual(slugify(""), "")

    def test_non_string_raises(self):
        with self.assertRaises(TypeError):
            slugify(123)


if __name__ == "__main__":
    unittest.main()
''',
    "wrong": '''def slugify(text):
    """Turn a title into a URL slug."""
    return "-".join(text.split(" ")).lower()
''',
    "partial": '''import re


def slugify(text):
    """Turn a title into a URL slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower())
''',
    "correct": '''import re


def slugify(text):
    """Turn a title into a URL slug."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
''',
}


CART_TOTAL: Bug = {
    "id": "cart",
    "tier": "easy",
    "title": "cart_total() subtracts the discount as money",
    "issue": (
        "cart_total(items, discount) takes (price, quantity) pairs and a discount given as a "
        "percentage, but it subtracts the discount as a flat amount. The total must apply the "
        "percentage and be rounded to 2 decimals. A discount outside 0..100 must raise ValueError."
    ),
    "target": "cart.py",
    "buggy": '''def cart_total(items, discount=0):
    """Total of (price, quantity) pairs after a percentage discount."""
    subtotal = sum(price * qty for price, qty in items)
    return subtotal - discount
''',
    "tests": '''import unittest

from cart import cart_total


class TestCartTotal(unittest.TestCase):
    def test_no_discount(self):
        self.assertEqual(cart_total([(10.0, 2), (5.0, 1)]), 25.0)

    def test_percentage_discount(self):
        self.assertEqual(cart_total([(20.0, 1)], 25), 15.0)

    def test_rounds_to_cents(self):
        self.assertEqual(cart_total([(9.99, 3)], 10), 26.97)

    def test_empty_cart(self):
        self.assertEqual(cart_total([], 50), 0.0)

    def test_discount_over_100_raises(self):
        with self.assertRaises(ValueError):
            cart_total([(10.0, 1)], 150)

    def test_negative_discount_raises(self):
        with self.assertRaises(ValueError):
            cart_total([(10.0, 1)], -5)


if __name__ == "__main__":
    unittest.main()
''',
    "wrong": '''def cart_total(items, discount=0):
    """Total of (price, quantity) pairs after a percentage discount."""
    subtotal = sum(price * qty for price, qty in items)
    return round(subtotal * discount / 100, 2)
''',
    "partial": '''def cart_total(items, discount=0):
    """Total of (price, quantity) pairs after a percentage discount."""
    subtotal = sum(price * qty for price, qty in items)
    return round(subtotal * (1 - discount / 100), 2)
''',
    "correct": '''def cart_total(items, discount=0):
    """Total of (price, quantity) pairs after a percentage discount."""
    if not 0 <= discount <= 100:
        raise ValueError("discount must be between 0 and 100")
    subtotal = sum(price * qty for price, qty in items)
    return round(subtotal * (1 - discount / 100), 2)
''',
}


AVERAGE: Bug = {
    "id": "average",
    "tier": "easy",
    "title": "average() truncates and crashes on empty input",
    "issue": (
        "average(values) should return the true arithmetic mean rounded to 2 decimals, "
        "but it uses integer division. An empty list should return 0.0 instead of crashing. "
        "Non-numeric values must still raise TypeError."
    ),
    "target": "stats.py",
    "buggy": '''def average(values):
    """Mean of a list of numbers."""
    return sum(values) // len(values)
''',
    "tests": '''import unittest

from stats import average


class TestAverage(unittest.TestCase):
    def test_whole_mean(self):
        self.assertEqual(average([2, 4, 6]), 4.0)

    def test_fractional_mean(self):
        self.assertEqual(average([1, 2]), 1.5)

    def test_rounds_to_two_decimals(self):
        self.assertEqual(average([1, 2, 2]), 1.67)

    def test_empty_list_is_zero(self):
        self.assertEqual(average([]), 0.0)

    def test_single_value(self):
        self.assertEqual(average([5]), 5.0)

    def test_non_numeric_raises(self):
        with self.assertRaises(TypeError):
            average(["a", "b"])


if __name__ == "__main__":
    unittest.main()
''',
    "wrong": '''def average(values):
    """Mean of a list of numbers."""
    return round(sum(values) / (len(values) + 1), 2)
''',
    "partial": '''def average(values):
    """Mean of a list of numbers."""
    return round(sum(values) / len(values), 2)
''',
    "correct": '''def average(values):
    """Mean of a list of numbers."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)
''',
}


EASY_BUGS: tuple[Bug, ...] = (PAGINATE, SLUGIFY, CART_TOTAL, AVERAGE)

from app.bugs_hard import HARD_BUGS  # noqa: E402

BUGS: dict[str, Bug] = {bug["id"]: bug for bug in (*EASY_BUGS, *HARD_BUGS)}


def bugs_in_tier(tier: str | None) -> list[Bug]:
    return [b for b in BUGS.values() if tier in (None, "all", b.get("tier", "easy"))]


def get_bug(bug_id: str) -> Bug | None:
    return BUGS.get(bug_id)


def test_filename(bug: Bug) -> str:
    return f"test_{bug['target']}"


def files_for(bug: Bug, code: str) -> dict[str, str]:
    """The two files a sandbox needs: the candidate source and its tests."""
    return {bug["target"]: code, test_filename(bug): bug["tests"]}
