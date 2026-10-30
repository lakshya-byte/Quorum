"""Core stock bookkeeping: items, removal, restock, adjustments and the audit trail."""
from .models import Item, StockError
from .utils import normalise_sku

MAX_HISTORY = 1000


class StockBase:
    def __init__(self):
        self._items = {}
        self._reserved = {}
        self._history = []

    def add_item(self, sku, name, unit_price, quantity=0, reorder_level=5, tags=None):
        sku = normalise_sku(sku)
        if not sku:
            raise StockError("sku required")
        if sku in self._items:
            raise StockError(f"duplicate sku {sku}")
        if unit_price < 0:
            raise StockError("price must be >= 0")
        if quantity < 0:
            raise StockError("quantity must be >= 0")
        self._items[sku] = Item(sku, name, unit_price, quantity, reorder_level, list(tags or []))
        self._log("add", sku, quantity)
        return self._items[sku]

    def get(self, sku):
        sku = normalise_sku(sku)
        if sku not in self._items:
            raise StockError(f"unknown sku {sku}")
        return self._items[sku]

    def items(self):
        return list(self._items.values())

    def remove(self, sku, qty):
        item = self.get(sku)
        if qty <= 0:
            raise StockError("qty must be positive")
        available = item.quantity - self._reserved.get(item.sku, 0)
        if qty > available:
            raise StockError(f"cannot remove {qty} of {item.sku}: only {available} available")
        item.quantity -= qty
        self._log("remove", item.sku, qty)
        return item.quantity

    def restock(self, sku, qty):
        item = self.get(sku)
        if qty <= 0:
            raise StockError("qty must be positive")
        item.quantity += qty
        self._log("restock", item.sku, qty)
        return item.quantity

    def adjust(self, sku, delta, reason=""):
        item = self.get(sku)
        if delta == 0:
            return item.quantity
        if delta < 0 and -delta > item.quantity - self._reserved.get(item.sku, 0):
            raise StockError("adjustment would go below reserved stock")
        if delta > 0 and reason == "":
            reason = "manual"
        elif delta < 0 and reason == "":
            reason = "shrinkage"
        item.quantity += delta
        self._log("adjust:" + reason, item.sku, delta)
        return item.quantity

    def _log(self, action, sku, qty):
        self._history.append((action, sku, qty))
        if len(self._history) > MAX_HISTORY:
            del self._history[: len(self._history) - MAX_HISTORY]

    def history(self, sku=None):
        if sku is None:
            return list(self._history)
        sku = normalise_sku(sku)
        return [h for h in self._history if h[1] == sku]
