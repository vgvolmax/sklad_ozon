"""Server-only daily order evidence, independent of route planning."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DailyOrderMetric:
    sku: str
    day: date
    quantity: int
    spp: Decimal | None
    buyer_price_mean: Decimal | None = None
    spp_priced_qty: int = 0
    buyer_priced_qty: int = 0


@dataclass(frozen=True, slots=True)
class DailyOrderEvidence:
    period_start: date
    period_end: date
    complete: bool
    incomplete_skus: tuple[str, ...]
    days: tuple[DailyOrderMetric, ...]
