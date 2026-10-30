import unittest

from inventory import Item, Stock, build_order, discount_percent, price_for


class BulkDiscountTests(unittest.TestCase):
    def setUp(self):
        self.item = Item("A", "a", 2.0)

    def test_no_discount_below_ten(self):
        self.assertEqual(price_for(self.item, 9), 18.0)
        self.assertEqual(discount_percent(9), 0)

    def test_five_percent_from_ten(self):
        self.assertEqual(price_for(self.item, 10), 19.0)
        self.assertEqual(discount_percent(10), 5)
        self.assertEqual(discount_percent(49), 5)

    def test_ten_percent_from_fifty(self):
        self.assertEqual(price_for(self.item, 50), 90.0)
        self.assertEqual(discount_percent(50), 10)

    def test_fifteen_percent_from_hundred(self):
        self.assertEqual(price_for(self.item, 100), 170.0)
        self.assertEqual(discount_percent(1000), 15)

    def test_zero_and_negative(self):
        self.assertEqual(price_for(self.item, 0), 0.0)
        with self.assertRaises(ValueError):
            price_for(self.item, -1)

    def test_order_total_uses_tiers(self):
        stock = Stock()
        stock.add_item("a", "Alpha", 2.0, 200)
        order = build_order(stock, "o1", {"a": 60})
        self.assertEqual(order.total(), 108.0)


if __name__ == "__main__":
    unittest.main()
