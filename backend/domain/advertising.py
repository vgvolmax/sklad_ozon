"""Normalized advertising costs and all-order revenue, without raw uploads."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class AdvertisingDay:
    campaign_id: str
    sku: str
    day: date
    spend: Decimal


@dataclass(frozen=True, slots=True)
class AdvertisingReport:
    campaign_id: str
    period_start: date
    period_end: date
    filename: str
    days: tuple[AdvertisingDay, ...]
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class AdvertisingCampaign:
    campaign_id: str
    filename: str
    imported_at: str


@dataclass(frozen=True, slots=True)
class OrderRevenueDay:
    sku: str
    day: date
    revenue: Decimal


@dataclass(frozen=True, slots=True)
class OrderRevenueEvidence:
    period_start: date
    period_end: date
    complete: bool
    incomplete_skus: tuple[str, ...]
    days: tuple[OrderRevenueDay, ...]
