"""Server-only daily order evidence, independent of route planning."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.analytics.daily import DailyFulfillmentCell
    from backend.economics.route_opportunity import RouteOpportunity


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


@dataclass(frozen=True, slots=True)
class EconomicsPeriodEvidence:
    """Dated delivered routes and immutable current-rate valuations, server only."""
    period_start: date
    period_end: date
    daily_routes: tuple['DailyFulfillmentCell', ...]
    route_economics: tuple['RouteOpportunity', ...]
    complete: bool = True
