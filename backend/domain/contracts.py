"""Immutable data crossing the normalized domain boundary."""

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar


class OrderLifecycle(str, Enum):
    FULFILLED = "fulfilled"
    IN_PROGRESS = "in_progress"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ReportMeta:
    source_name: str
    imported_at: str
    report_generated_at: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    recommendation_horizon_days: int | None = None


@dataclass(frozen=True, slots=True)
class ImportDiagnostic:
    severity: str
    code: str
    message: str
    row: int | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class OrderRecord:
    sku: str
    quantity: int
    origin_cluster: str
    destination_cluster: str
    lifecycle: OrderLifecycle = OrderLifecycle.UNKNOWN
    accepted_at: str = ""
    planned_ship_at: str | None = None
    handed_to_delivery_at: str | None = None
    delivered_at: str | None = None
    raw_status: str = ""
    article: str = ""
    product_name: str = ""
    seller_price: float = 0.0
    origin_warehouse: str | None = None
    volumetric_weight_kg: float | None = None


RecordT = TypeVar("RecordT")


@dataclass(frozen=True, slots=True)
class ImportResult(Generic[RecordT]):
    records: tuple[RecordT, ...]
    diagnostics: tuple[ImportDiagnostic, ...]
    meta: ReportMeta
