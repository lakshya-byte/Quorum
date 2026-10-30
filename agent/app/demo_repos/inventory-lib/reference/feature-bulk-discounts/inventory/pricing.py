"""Pricing rules."""
from .utils import money

# (minimum quantity, percent off), checked from the largest tier down
DISCOUNT_TIERS = ((100, 15), (50, 10), (10, 5))


def discount_percent(qty):
    """Percent off the unit price for buying `qty` units at once."""
    for minimum, percent in DISCOUNT_TIERS:
        if qty >= minimum:
            return percent
    return 0


def price_for(item, qty):
    """Total price for `qty` units of `item`, including the bulk discount tier."""
    if qty < 0:
        raise ValueError("qty must be >= 0")
    return money(item.unit_price * qty * (100 - discount_percent(qty)) / 100)


def apply_coupon(total, percent):
    """Take `percent` percent off `total`."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return money(total * (100 - percent) / 100)
