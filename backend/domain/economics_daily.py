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


@dataclass(frozen=True, slots=True)
class DailyOrderEvidence:
    period_start: date
    period_end: date
    complete: bool
    incomplete_skus: tuple[str, ...]
    days: tuple[DailyOrderMetric, ...]
