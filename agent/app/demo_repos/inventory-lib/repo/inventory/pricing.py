"""Pricing rules."""
from .utils import money


def price_for(item, qty):
    """Total price for `qty` units of `item` (no discounts yet)."""
    if qty < 0:
        raise ValueError("qty must be >= 0")
    return money(item.unit_price * qty)


def apply_coupon(total, percent):
    """Take `percent` percent off `total`."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return money(total * (100 - percent) / 100)
