"""Reservations: hold stock for pending orders."""
from .models import StockError


class ReservationMixin:
    def reserve(self, sku, qty):
        item = self.get(sku)
        if qty <= 0:
            raise StockError("qty must be positive")
        free = item.quantity - self._reserved.get(item.sku, 0)
        if qty > free:
            raise StockError(f"cannot reserve {qty} of {item.sku}: only {free} free")
        self._reserved[item.sku] = self._reserved.get(item.sku, 0) + qty
        self._log("reserve", item.sku, qty)
        return self._reserved[item.sku]

    def release(self, sku, qty):
        item = self.get(sku)
        held = self._reserved.get(item.sku, 0)
        if qty <= 0 or qty > held:
            raise StockError(f"cannot release {qty}: {held} reserved")
        self._reserved[item.sku] = held - qty
        if self._reserved[item.sku] == 0:
            del self._reserved[item.sku]
        self._log("release", item.sku, qty)
        return held - qty

    def reserved(self, sku):
        return self._reserved.get(self.get(sku).sku, 0)
