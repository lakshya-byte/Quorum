"""CSV import / export."""
import csv
import io

from .models import StockError


class CsvMixin:
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
