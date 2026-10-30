import unittest

from inventory import Item, apply_coupon, price_for


class PricingTests(unittest.TestCase):
    def test_price_for_is_linear_today(self):
        item = Item("A", "a", 2.0)
        self.assertEqual(price_for(item, 3), 6.0)
        self.assertEqual(price_for(item, 0), 0.0)

    def test_negative_qty(self):
        with self.assertRaises(ValueError):
            price_for(Item("A", "a", 2.0), -1)

    def test_coupon(self):
        self.assertEqual(apply_coupon(100.0, 15), 85.0)
        with self.assertRaises(ValueError):
            apply_coupon(10, 101)


if __name__ == "__main__":
    unittest.main()
