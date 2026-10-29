import unittest

from booking.calendar import Calendar
from booking.intervals import overlaps


class TestBackToBackReproducer(unittest.TestCase):
    def test_a_booking_that_starts_when_the_other_ends_is_allowed(self):
        self.assertFalse(overlaps(9, 10, 10, 11))
        cal = Calendar()
        cal.book(9, 10)
        cal.book(10, 11)

    def test_a_booking_that_ends_when_the_other_starts_is_allowed(self):
        self.assertFalse(overlaps(10, 11, 9, 10))


if __name__ == "__main__":
    unittest.main()
