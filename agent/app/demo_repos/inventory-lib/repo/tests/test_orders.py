import unittest

from inventory import Stock, StockError, build_order


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.stock = Stock()
        self.stock.add_item("a", "Alpha", 2.0, 20)
        self.stock.add_item("b", "Beta", 5.0, 5)

    def test_build_order_reduces_stock(self):
        order = build_order(self.stock, "o1", {"a": 3, "b": 2})
        self.assertEqual(order.total(), 16.0)
        self.assertEqual(self.stock.get("a").quantity, 17)

    def test_not_enough(self):
        with self.assertRaises(StockError):
            build_order(self.stock, "o2", {"b": 6})
        self.assertEqual(self.stock.get("b").quantity, 5)


if __name__ == "__main__":
    unittest.main()
