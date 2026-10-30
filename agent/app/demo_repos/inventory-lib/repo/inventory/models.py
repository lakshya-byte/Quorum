"""Plain data types."""
from dataclasses import dataclass, field


class StockError(Exception):
    """Raised for impossible stock operations."""


@dataclass
class Item:
    sku: str
    name: str
    unit_price: float
    quantity: int = 0
    reorder_level: int = 5
    tags: list = field(default_factory=list)
