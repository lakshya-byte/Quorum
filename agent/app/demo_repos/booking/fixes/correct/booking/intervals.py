"""Interval helpers. Intervals are half-open: [start, end)."""


def overlaps(a_start, a_end, b_start, b_end):
    """True when the two half-open intervals share any time. Back-to-back intervals do not overlap."""
    return a_start < b_end and b_start < a_end
