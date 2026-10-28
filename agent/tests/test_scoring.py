from app.scoring import changed_lines, parse_unittest, score

PASSING = """......
----------------------------------------------------------------------
Ran 6 tests in 0.001s

OK
"""

FAILING = """F.E..F
======================================================================
FAIL: test_first_page (test_pagination.TestPaginate.test_first_page)
----------------------------------------------------------------------
Ran 6 tests in 0.002s

FAILED (failures=2, errors=1)
"""

SYNTAX_ERROR = """E
======================================================================
ERROR: test_pagination (unittest.loader._FailedTest.test_pagination)
ImportError: Failed to import test module: test_pagination
  File "/tmp/x/pagination.py", line 1
    def broken(:
SyntaxError: invalid syntax
----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
"""


def test_passing_output() -> None:
    assert parse_unittest(PASSING) == (6, 6)


def test_failing_output_sums_failures_and_errors() -> None:
    assert parse_unittest(FAILING) == (3, 6)


def test_syntax_error_scores_zero() -> None:
    assert parse_unittest(SYNTAX_ERROR) == (0, 1)
    assert score(0, 1, "a\n", "b\n") == 0.0


def test_no_tests_ran() -> None:
    assert parse_unittest("TIMEOUT") == (0, 0)
    assert score(0, 0, "", "") == 0.0


def test_smaller_patch_wins_tie() -> None:
    old = "def f(x):\n    return x\n"
    small = "def f(x):\n    return x + 1\n"
    big = "def f(x):\n    y = x\n    y = y + 1\n    return y\n"
    assert changed_lines(old, small) == 2
    assert score(6, 6, old, small) > score(6, 6, old, big)
    assert score(6, 6, old, old) == 1.0


def test_penalty_is_capped() -> None:
    old = "\n".join(f"a{i}" for i in range(200))
    new = "\n".join(f"b{i}" for i in range(200))
    assert score(6, 6, old, new) == 1.0 - 0.05
