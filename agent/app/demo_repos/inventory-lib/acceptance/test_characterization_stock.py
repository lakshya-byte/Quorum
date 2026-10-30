"""Characterization tests: golden behaviour of Stock captured from the ORIGINAL implementation."""
import unittest

from inventory import Stock, StockError


def scenario():
    s = Stock()
    s.add_item("w1", "Widget", 2.5, 10, tags=["tools"])
    s.add_item("g2", "Gadget", 10.0, 3, reorder_level=4, tags=["tools", "new"])
    s.add_item("d3", "Doohickey", 1.0, 0)
    s.reserve("w1", 4)
    s.remove("w1", 2)
    s.adjust("g2", 2, "recount")
    s.adjust("d3", 5)
    s.restock("d3", 1)
    return s


class CharacterizationTests(unittest.TestCase):
    def test_history_is_exact(self):
        self.assertEqual(scenario().history(), [
            ("add", "W1", 10), ("add", "G2", 3), ("add", "D3", 0), ("reserve", "W1", 4), ("remove", "W1", 2),
            ("adjust:recount", "G2", 2), ("adjust:manual", "D3", 5), ("restock", "D3", 1)])

    def test_summary_and_valuation(self):
        s = scenario()
        self.assertEqual(s.summary(), {
            "skus": 3, "units": 19, "value": 76.0,
            "by_tag": {"tools": {"skus": 2, "units": 13}, "new": {"skus": 1, "units": 5}, "untagged": {"skus": 1, "units": 6}}})
        self.assertEqual(s.valuation("tools"), 70.0)

    def test_csv_golden(self):
        self.assertEqual(scenario().export_csv(),
                         "sku,name,unit_price,quantity,reorder_level,tags\n"
                         "D3,Doohickey,1.00,6,5,\nG2,Gadget,10.00,5,4,tools|new\nW1,Widget,2.50,8,5,tools\n")

    def test_error_messages(self):
        s = scenario()
        with self.assertRaises(StockError) as ctx:
            s.remove("w1", 5)
        self.assertEqual(str(ctx.exception), "cannot remove 5 of W1: only 4 available")
        with self.assertRaises(StockError) as ctx:
            s.release("g2", 1)
        self.assertEqual(str(ctx.exception), "cannot release 1: 0 reserved")
        with self.assertRaises(StockError) as ctx:
            s.get("nope")
        self.assertEqual(str(ctx.exception), "unknown sku NOPE")

    def test_search_and_low_stock(self):
        s = scenario()
        self.assertEqual([i.sku for i in s.search("gad")], ["G2"])
        self.assertEqual(s.low_stock(), [])
        s.remove("g2", 1)
        self.assertEqual([i.sku for i in s.low_stock()], ["G2"])

    def test_history_cap(self):
        s = Stock()
        s.add_item("x", "X", 1.0, 1)
        for _ in range(1200):
            s.restock("x", 1)
        self.assertEqual(len(s.history()), 1000)


if __name__ == "__main__":
    unittest.main()
