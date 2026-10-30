import unittest

from inventory import Stock, StockError


def make():
    s = Stock()
    s.add_item("a1", "Widget", 2.5, 10, tags=["tools"])
    s.add_item("b2", "Gadget", 10.0, 3, reorder_level=4, tags=["tools", "new"])
    s.add_item("c3", "Doohickey", 1.0, 0)
    return s


class StockTests(unittest.TestCase):
    def test_add_and_get(self):
        s = make()
        self.assertEqual(s.get("A1").name, "Widget")
        with self.assertRaises(StockError):
            s.add_item("a1", "dup", 1)

    def test_remove_and_restock(self):
        s = make()
        self.assertEqual(s.remove("a1", 4), 6)
        self.assertEqual(s.restock("a1", 1), 7)
        with self.assertRaises(StockError):
            s.remove("a1", 100)

    def test_reserve_blocks_remove(self):
        s = make()
        s.reserve("a1", 8)
        with self.assertRaises(StockError):
            s.remove("a1", 3)
        self.assertEqual(s.release("a1", 8), 0)
        self.assertEqual(s.remove("a1", 3), 7)

    def test_adjust(self):
        s = make()
        self.assertEqual(s.adjust("a1", -2), 8)
        self.assertEqual(s.adjust("a1", 5, "recount"), 13)
        self.assertEqual(s.history("a1")[-1][0], "adjust:recount")

    def test_low_stock_and_search(self):
        s = make()
        self.assertEqual([i.sku for i in s.low_stock()], ["B2", "C3"])
        self.assertEqual([i.sku for i in s.search(tag="new")], ["B2"])
        self.assertEqual([i.sku for i in s.search(in_stock_only=True)], ["A1", "B2"])

    def test_valuation_summary(self):
        s = make()
        self.assertEqual(s.valuation(), 55.0)
        self.assertEqual(s.valuation("new"), 30.0)
        self.assertEqual(s.summary()["by_tag"]["tools"], {"skus": 2, "units": 13})

    def test_csv_roundtrip(self):
        s = make()
        text = s.export_csv()
        t = Stock()
        self.assertEqual(t.import_csv(text), 3)
        self.assertEqual(t.export_csv(), text)


if __name__ == "__main__":
    unittest.main()
