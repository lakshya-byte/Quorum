import unittest

from wordstats.report import format_report


class TestReport(unittest.TestCase):
    def test_lines(self):
        self.assertEqual(format_report("b a a", 2), "a: 2\nb: 1")

    def test_case_is_merged(self):
        self.assertEqual(format_report("Go go", 1), "go: 2")


if __name__ == "__main__":
    unittest.main()
