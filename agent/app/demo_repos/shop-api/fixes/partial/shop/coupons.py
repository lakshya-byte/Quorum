"""Coupon helpers. All amounts are integer cents."""


def apply_percent(amount_cents, percent):
    """Return the discount in cents for `percent` off `amount_cents`, rounded half up."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return (amount_cents * percent + 50) // 100
