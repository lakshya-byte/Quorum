import unittest

from inventory import Stock, stock_report


class ReportTests(unittest.TestCase):
    def test_report(self):
        s = Stock()
        s.add_item("a", "Alpha", 2.0, 20)
        s.add_item("b", "Beta", 5.0, 2)
        text = stock_report(s.items())
        self.assertIn("LOW", text.splitlines()[1])
        self.assertTrue(text.endswith("TOTAL VALUE 50.00"))


if __name__ == "__main__":
    unittest.main()
