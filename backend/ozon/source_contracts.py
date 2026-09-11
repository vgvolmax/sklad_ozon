"""Immutable, normalized and PII-safe Ozon source contracts."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

MOSCOW_BUSINESS_TZ = timezone(timedelta(hours=3))
SOURCE_TIMEZONE = "UTC+03:00"


def source_business_date(synced_at_utc: datetime) -> date:
    if synced_at_utc.tzinfo is None:
        raise ValueError("synced_at_utc must be timezone-aware")
    return synced_at_utc.astimezone(MOSCOW_BUSINESS_TZ).date()


@dataclass(frozen=True, slots=True)
class EndpointEvidence:
    name: str
    fetched_at_utc: str
    record_count: int
    complete: bool
    diagnostics: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class SellerWarehouse:
    seller_warehouse_id: int
    name: str | None
    address: str | None
    is_active: bool
    is_pickup: bool | None


@dataclass(frozen=True, slots=True)
class Cluster:
    cluster_id: int
    name: str


@dataclass(frozen=True, slots=True)
class PlacementZoneEvidence:
    sku: str
    zones: tuple[str, ...]
    complete: bool = True


@dataclass(frozen=True, slots=True)
class OzonSourceSnapshot:
    source_snapshot_id: str
    synced_at_utc: str
    source_as_of: date
    source_timezone: str
    history_from: date
    history_to: date
    orders: tuple[Any, ...]
    availability: tuple[Any, ...]
    operational_seller_stock: tuple[Any, ...]
    clusters: tuple[Any, ...]
    seller_warehouses: tuple[SellerWarehouse, ...]
    placement_zones: tuple[Any, ...]
    endpoint_evidence: tuple[EndpointEvidence, ...]
    diagnostics: tuple[Any, ...]
    credential_context_id: str | None = None
