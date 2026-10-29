import unittest

from shop.cart import Cart


class TestCouponTotalReproducer(unittest.TestCase):
    def test_coupon_total_rounds_the_discount_and_keeps_shipping_full_price(self):
        cart = Cart()
        cart.add("widget", 1005)
        cart.coupon_percent = 10
        # items 1005 - discount 101 (rounded half up) + shipping 500 (not discounted)
        self.assertEqual(cart.total(), 1404)
        self.assertEqual(cart.total() - cart.subtotal(), 500 - 101)


if __name__ == "__main__":
    unittest.main()
