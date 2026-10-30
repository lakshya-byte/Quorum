"""Orders: price lines against stock."""
from .models import StockError
from .pricing import price_for
from .utils import money


class Order:
    def __init__(self, order_id):
        self.order_id = order_id
        self.lines = []

    def add_line(self, item, qty):
        self.lines.append((item, qty))

    def total(self):
        return money(sum(price_for(item, qty) for item, qty in self.lines))


def build_order(stock, order_id, wanted):
    """`wanted` maps sku -> qty. Reserves stock and returns the Order."""
    order = Order(order_id)
    for sku, qty in sorted(wanted.items()):
        item = stock.get(sku)
        if item.quantity < qty:
            raise StockError(f"not enough {sku}: have {item.quantity}, need {qty}")
        order.add_line(item, qty)
    for sku, qty in wanted.items():
        stock.remove(sku, qty)
    return order
