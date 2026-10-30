"""Stock management. (Monolithic on purpose: bookkeeping, reservations, valuation, CSV and audit in one file.)"""
import csv
import io

from .models import Item, StockError
from .utils import money, normalise_sku

LOW_FACTOR = 1
MAX_HISTORY = 1000


class Stock:
    def __init__(self):
        self._items = {}
        self._reserved = {}
        self._history = []

    # ---- basic bookkeeping ----------------------------------------------------------------
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

    # ---- reservations -----------------------------------------------------------------------
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

    # ---- queries and valuation ------------------------------------------------------------
    def low_stock(self):
        out = []
        for item in self._items.values():
            if item.quantity <= item.reorder_level * LOW_FACTOR:
                out.append(item)
        return sorted(out, key=lambda i: i.sku)

    def search(self, text="", tag=None, in_stock_only=False):
        text = text.lower()
        found = []
        for item in self._items.values():
            if text and text not in item.name.lower() and text not in item.sku.lower():
                continue
            if tag is not None and tag not in item.tags:
                continue
            if in_stock_only and item.quantity <= 0:
                continue
            found.append(item)
        return sorted(found, key=lambda i: i.sku)

    def valuation(self, tag=None):
        total = 0.0
        for item in self._items.values():
            if tag is None or tag in item.tags:
                total += item.unit_price * item.quantity
        return money(total)

    def summary(self):
        by_tag = {}
        for item in self._items.values():
            for tag in item.tags or ["untagged"]:
                entry = by_tag.setdefault(tag, {"skus": 0, "units": 0})
                entry["skus"] += 1
                entry["units"] += item.quantity
        return {"skus": len(self._items), "units": sum(i.quantity for i in self._items.values()),
                "value": self.valuation(), "by_tag": by_tag}

    # ---- csv ----------------------------------------------------------------------------------
    def export_csv(self):
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["sku", "name", "unit_price", "quantity", "reorder_level", "tags"])
        for item in sorted(self._items.values(), key=lambda i: i.sku):
            writer.writerow([item.sku, item.name, f"{item.unit_price:.2f}", item.quantity, item.reorder_level,
                             "|".join(item.tags)])
        return buf.getvalue()

    def import_csv(self, text):
        reader = csv.DictReader(io.StringIO(text))
        count = 0
        for row in reader:
            try:
                tags = [t for t in (row.get("tags") or "").split("|") if t]
                self.add_item(row["sku"], row["name"], float(row["unit_price"]), int(row["quantity"]),
                              int(row.get("reorder_level") or 5), tags)
            except (KeyError, ValueError) as exc:
                raise StockError(f"bad csv row {row!r}: {exc}") from None
            count += 1
        return count

    # ---- audit ----------------------------------------------------------------------------------
    def _log(self, action, sku, qty):
        self._history.append((action, sku, qty))
        if len(self._history) > MAX_HISTORY:
            del self._history[: len(self._history) - MAX_HISTORY]

    def history(self, sku=None):
        if sku is None:
            return list(self._history)
        sku = normalise_sku(sku)
        return [h for h in self._history if h[1] == sku]
