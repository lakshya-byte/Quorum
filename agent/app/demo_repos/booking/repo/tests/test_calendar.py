import unittest

from booking.calendar import Calendar, ConflictError


class TestCalendar(unittest.TestCase):
    def test_books_a_free_slot(self):
        cal = Calendar()
        cal.book(9, 10)
        self.assertEqual(cal.bookings, [(9, 10)])

    def test_rejects_an_overlap(self):
        cal = Calendar()
        cal.book(9, 11)
        with self.assertRaises(ConflictError):
            cal.book(10, 12)

    def test_rejects_an_empty_slot(self):
        with self.assertRaises(ValueError):
            Calendar().book(10, 10)


if __name__ == "__main__":
    unittest.main()
