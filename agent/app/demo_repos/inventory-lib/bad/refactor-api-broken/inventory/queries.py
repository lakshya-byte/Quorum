"""Read-only queries and valuation."""
from .utils import money

LOW_FACTOR = 1


class QueryMixin:
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
