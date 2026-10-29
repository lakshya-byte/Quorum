import unittest

from shop.coupons import apply_percent


class TestApplyPercent(unittest.TestCase):
    def test_ten_percent(self):
        self.assertEqual(apply_percent(1000, 10), 100)

    def test_rounds_half_up(self):
        self.assertEqual(apply_percent(1005, 10), 101)

    def test_rounds_half_up_small_amount(self):
        self.assertEqual(apply_percent(15, 50), 8)

    def test_zero_percent(self):
        self.assertEqual(apply_percent(1234, 0), 0)

    def test_invalid_percent(self):
        with self.assertRaises(ValueError):
            apply_percent(100, 101)


if __name__ == "__main__":
    unittest.main()
