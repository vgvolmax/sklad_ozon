"""Immutable data crossing the normalized domain boundary."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar


class SourceMode(str, Enum):
    """The single, domain-neutral owner of an analysis run's source data."""

    API = "api"
    FILES = "files"


@dataclass(frozen=True, slots=True)
class AnalysisSourceCoverage:
    """Source-level evidence required by generic Need calculation."""

    orders_fbo_complete: bool
    orders_fbs_complete: bool
    fbo_stock_complete: bool
    inbound_complete: bool

    @property
    def demand_complete(self) -> bool:
        return self.orders_fbo_complete and self.orders_fbs_complete


class RestrictionCapacityKind(str, Enum):
    UNKNOWN = "unknown"
    ZERO = "zero"
    FINITE = "finite"
    UNLIMITED = "unlimited"


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
    record_sources: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TariffRow:
    origin_cluster_id: str
    destination_cluster_id: str
    min_volume_liters: Decimal
    max_volume_liters: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None
    logistics_fee: Decimal


@dataclass(frozen=True, slots=True)
class ProductEconomicsInput:
    sku: str
    article: str
    cost: Decimal | None
    available_qty: int | None
    price: Decimal | None
    commission_rate: Decimal | None
    volume_liters: Decimal | None
