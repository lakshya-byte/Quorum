import unittest

from shop.cart import Cart


def cart_with(price, qty=1, coupon=0):
    cart = Cart()
    cart.add("widget", price, qty)
    cart.coupon_percent = coupon
    return cart


class TestCart(unittest.TestCase):
    def test_subtotal(self):
        self.assertEqual(cart_with(250, qty=3).subtotal(), 750)

    def test_shipping_is_charged_below_the_threshold(self):
        self.assertEqual(cart_with(1000).shipping(), 500)

    def test_shipping_is_free_from_the_threshold(self):
        self.assertEqual(cart_with(5000).shipping(), 0)

    def test_total_without_coupon(self):
        self.assertEqual(cart_with(1000).total(), 1500)

    def test_coupon_does_not_discount_shipping(self):
        self.assertEqual(cart_with(2000, coupon=10).total(), 2300)

    def test_coupon_discount_rounds_half_up(self):
        self.assertEqual(cart_with(1005, coupon=10).total(), 1404)

    def test_bad_quantity(self):
        with self.assertRaises(ValueError):
            Cart().add("widget", 100, qty=0)


if __name__ == "__main__":
    unittest.main()
