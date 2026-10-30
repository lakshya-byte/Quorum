"""Text reports."""
from .utils import money


def format_line(item):
    flag = " LOW" if item.quantity <= item.reorder_level else ""
    return f"{item.sku:<8}{item.name:<20}{item.quantity:>5} x {money(item.unit_price):>8.2f}{flag}"


def stock_report(items):
    lines = [format_line(i) for i in sorted(items, key=lambda i: i.sku)]
    total = money(sum(i.unit_price * i.quantity for i in items))
    return "\n".join(lines + [f"TOTAL VALUE {total:.2f}"])
