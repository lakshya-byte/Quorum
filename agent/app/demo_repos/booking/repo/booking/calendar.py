"""A room calendar that refuses double bookings."""
from booking.intervals import overlaps


class ConflictError(Exception):
    pass


class Calendar:
    def __init__(self):
        self.bookings = []

    def is_free(self, start, end):
        return not any(overlaps(start, end, s, e) for s, e in self.bookings)

    def book(self, start, end):
        if start >= end:
            raise ValueError("start must be before end")
        if not self.is_free(start, end):
            raise ConflictError(f"{start}-{end} overlaps an existing booking")
        self.bookings.append((start, end))
