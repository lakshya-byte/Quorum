import unittest

from booking.intervals import overlaps


class TestOverlaps(unittest.TestCase):
    def test_identical(self):
        self.assertTrue(overlaps(9, 10, 9, 10))

    def test_partial_overlap(self):
        self.assertTrue(overlaps(9, 11, 10, 12))

    def test_contained(self):
        self.assertTrue(overlaps(8, 12, 9, 10))

    def test_far_apart(self):
        self.assertFalse(overlaps(9, 10, 13, 14))

    def test_far_apart_reversed(self):
        self.assertFalse(overlaps(13, 14, 9, 10))


if __name__ == "__main__":
    unittest.main()
