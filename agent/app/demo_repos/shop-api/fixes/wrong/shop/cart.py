"""A shopping cart. All amounts are integer cents."""
from shop.coupons import apply_percent

SHIPPING_CENTS = 500
FREE_SHIPPING_FROM = 5000


class Cart:
    def __init__(self):
        self.items = []
        self.coupon_percent = 0

    def add(self, name, price_cents, qty=1):
        if qty < 1:
            raise ValueError("qty must be at least 1")
        self.items.append((name, price_cents, qty))

    def subtotal(self):
        return sum(price * qty for _, price, qty in self.items)

    def shipping(self):
        return 0 if self.subtotal() >= FREE_SHIPPING_FROM else SHIPPING_CENTS

    def total(self):
        """Items minus the coupon."""
        items = self.subtotal()
        return items - apply_percent(items, self.coupon_percent)
