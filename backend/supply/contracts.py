"""Immutable contracts for supply feasibility and placement assessment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from datetime import date

from backend.domain.signals import RecommendationDistortionSignal, SignalConfidence
from backend.domain.contracts import RestrictionCapacityKind, SourceMode

if TYPE_CHECKING:
    from backend.economics import UnitEconomicsResult


def _require_nonblank(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonblank")


def _require_nonnegative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


class PlacementSource(str, Enum):
    OBSERVED = "observed"
    RECOMMENDED = "recommended"
    COUNTERFACTUAL = "counterfactual"


class AllocationObjective(str, Enum):
    MAX_PROFIT = "max_profit"
    MAX_MARGIN = "max_margin"


class PlanFamily(str, Enum):
    SAFE = "safe"
    CALCULATED = "calculated"


class RouteConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RestrictionEligibility(str, Enum):
    UNKNOWN = "unknown"
    ALLOWED = "allowed"
    INELIGIBLE = "ineligible"


class PlacementZoneKind(str, Enum):
    UNKNOWN = "unknown"
    SINGLE = "single"
    MULTIPLE = "multiple"


class PhysicalFeasibilityState(str, Enum):
    CONFIRMED_ALLOWED = "confirmed_allowed"
    CONFIRMED_BLOCKED = "confirmed_blocked"
    UNKNOWN_PENDING_LIVE_VALIDATION = "unknown_pending_live_validation"


@dataclass(frozen=True, slots=True)
class SupplyProductIdentity:
    sku: str
    article: str

    def __post_init__(self) -> None:
        _require_nonblank(self.sku, "sku")


@dataclass(frozen=True, slots=True)
class RestrictionCapacityEvidence:
    eligibility: RestrictionEligibility
    capacity_kind: RestrictionCapacityKind
    capacity_qty: int | None

    def __post_init__(self) -> None:
        if self.capacity_qty is not None and (isinstance(self.capacity_qty, bool) or not isinstance(self.capacity_qty, int)):
            raise TypeError("capacity_qty must be an int")
        if self.capacity_kind is RestrictionCapacityKind.FINITE:
            if self.capacity_qty is None or self.capacity_qty <= 0:
                raise ValueError("finite capacity must have a positive quantity")
        elif self.capacity_kind is RestrictionCapacityKind.ZERO:
            if self.capacity_qty != 0:
                raise ValueError("zero capacity must have quantity zero")
        elif self.capacity_qty is not None:
            raise ValueError("unknown/unlimited capacity must not have a quantity")


@dataclass(frozen=True, slots=True)
class OperationalSupplyFact:
    sku: str
    article: str
    cluster_id: str
    pack_multiple: int | None
    placement_zone_kind: PlacementZoneKind
    placement_zones: tuple[str, ...]
    restriction_eligibility: RestrictionEligibility
    capacity_kind: RestrictionCapacityKind
    capacity_qty: int | None
    restriction_report_date: date | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonblank(self.sku, "sku")
        _require_nonblank(self.cluster_id, "cluster_id")
        if self.pack_multiple is not None:
            if isinstance(self.pack_multiple, bool) or not isinstance(self.pack_multiple, int):
                raise TypeError("pack_multiple must be an int")
            if self.pack_multiple <= 0:
                raise ValueError("pack_multiple must be positive")
        RestrictionCapacityEvidence(
            self.restriction_eligibility, self.capacity_kind, self.capacity_qty)


@dataclass(frozen=True, slots=True)
class WarehouseCapability:
    warehouse: str
    cluster_id: str
    max_supply_qty: int | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.warehouse, "warehouse")
        _require_nonblank(self.cluster_id, "cluster_id")
        if self.max_supply_qty is not None:
            _require_nonnegative_int(self.max_supply_qty, "max_supply_qty")


@dataclass(frozen=True, slots=True)
class SupplyFeasibility:
    sku: str
    cluster_id: str
    allowed: bool | None
    max_supply_qty: int | None
    eligible_warehouses: tuple[str, ...]
    reasons: tuple[str, ...]
    physical_state: PhysicalFeasibilityState | None = None

    def __post_init__(self) -> None:
        if self.physical_state is None:
            object.__setattr__(self, "physical_state", (
                PhysicalFeasibilityState.CONFIRMED_ALLOWED if self.allowed
                else PhysicalFeasibilityState.CONFIRMED_BLOCKED))

    @property
    def analytical_allocation_allowed(self) -> bool:
        return (self.allowed is not False
                and self.physical_state is not PhysicalFeasibilityState.CONFIRMED_BLOCKED)


@dataclass(frozen=True, slots=True)
class PlacementInput:
    sku: str
    cluster_id: str
    ozon_recommended_qty: int
    sources: tuple[PlacementSource, ...]
    economics: UnitEconomicsResult
    distortion_signal: RecommendationDistortionSignal | None
    route_confidence: RouteConfidence
    demand_confidence: SignalConfidence
    calculated_need_qty: int | None = None

    def __post_init__(self) -> None:
        from backend.economics import UnitEconomicsResult

        _require_nonblank(self.sku, "sku")
        _require_nonblank(self.cluster_id, "cluster_id")
        _require_nonnegative_int(self.ozon_recommended_qty, "ozon_recommended_qty")
        if not isinstance(self.sources, tuple):
            raise TypeError("sources must be a tuple")
        if not self.sources:
            raise ValueError("sources must not be empty")
        if any(not isinstance(source, PlacementSource) for source in self.sources):
            raise TypeError("sources must contain PlacementSource values")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("sources must not contain duplicates")
        if not isinstance(self.economics, UnitEconomicsResult):
            raise TypeError("economics must be UnitEconomicsResult")
        if self.economics.sku != self.sku or self.economics.placement_cluster_id != self.cluster_id:
            raise ValueError("economics identity must match candidate SKU and cluster")
        if self.distortion_signal is not None:
            if not isinstance(self.distortion_signal, RecommendationDistortionSignal):
                raise TypeError("distortion_signal must be RecommendationDistortionSignal")
            if (self.distortion_signal.sku != self.sku
                    or self.distortion_signal.recommended_cluster_id != self.cluster_id):
                raise ValueError("distortion signal identity must match candidate SKU and cluster")
        if not isinstance(self.route_confidence, RouteConfidence):
            raise TypeError("route_confidence must be RouteConfidence")
        if not isinstance(self.demand_confidence, SignalConfidence):
            raise TypeError("demand_confidence must be SignalConfidence")
        if self.calculated_need_qty is not None:
            _require_nonnegative_int(self.calculated_need_qty, "calculated_need_qty")


@dataclass(frozen=True, slots=True)
class PlacementAssessment:
    sku: str
    cluster_id: str
    ozon_recommended_qty: int
    feasibility: SupplyFeasibility
    economics: UnitEconomicsResult
    distortion_signal: RecommendationDistortionSignal | None
    route_confidence: RouteConfidence
    demand_confidence: SignalConfidence
    status_codes: tuple[str, ...]
    calculated_need_qty: int | None = None


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    sku: str
    cluster_id: str
    allocation_qty: int
    automatic_ceiling_qty: int
    expected_profit_per_unit: Decimal | None
    expected_profit: Decimal
    eligible: bool
    reason_codes: tuple[str, ...]
    allocation_priority_rank: int | None = None

    def __post_init__(self) -> None:
        if self.allocation_priority_rank is not None:
            _require_nonnegative_int(self.allocation_priority_rank, "allocation_priority_rank")
            if self.allocation_priority_rank == 0:
                raise ValueError("allocation_priority_rank must be positive")


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    sku: str
    available_stock: int
    allocated_qty: int
    unallocated_stock: int
    eligible_capacity_qty: int
    objective_profit: Decimal
    decisions: tuple[AllocationDecision, ...]
    binding_reasons: tuple[str, ...]
    plan_family: PlanFamily
    objective: AllocationObjective


@dataclass(frozen=True, slots=True)
class ShippableDiagnostic:
    severity: str
    code: str
    message: str
    sku: str | None = None
    destination_cluster_id: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in {"error", "warning"}:
            raise ValueError("severity must be error or warning")
        _require_nonblank(self.code, "code")
        _require_nonblank(self.message, "message")
        if self.sku is not None:
            _require_nonblank(self.sku, "sku")
        if self.destination_cluster_id is not None:
            _require_nonblank(self.destination_cluster_id, "destination_cluster_id")


def _optional_nonnegative_int(value: object, name: str) -> None:
    if value is not None:
        _require_nonnegative_int(value, name)


@dataclass(frozen=True, slots=True)
class ShippableLine:
    sku: str
    article: str
    destination_cluster_id: str
    analytical_qty: int
    rounded_target_qty: int | None
    rounding_delta_qty: int | None
    allocation_priority_rank: int | None
    pack_multiple: int | None
    resolved_seller_stock: int
    shippable_qty: int | None
    unit_volume_l: Decimal | None
    total_volume_l: Decimal | None
    placement_zone_kind: PlacementZoneKind
    placement_zones: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonblank(self.sku, "sku")
        if not isinstance(self.article, str):
            raise TypeError("article must be a string")
        _require_nonblank(self.destination_cluster_id, "destination_cluster_id")
        _require_nonnegative_int(self.analytical_qty, "analytical_qty")
        _require_nonnegative_int(self.resolved_seller_stock, "resolved_seller_stock")
        for name in ("rounded_target_qty", "rounding_delta_qty", "shippable_qty"):
            _optional_nonnegative_int(getattr(self, name), name)
        if self.pack_multiple is not None:
            _require_nonnegative_int(self.pack_multiple, "pack_multiple")
            if self.pack_multiple == 0:
                raise ValueError("pack_multiple must be positive")
        if self.allocation_priority_rank is not None:
            _require_nonnegative_int(self.allocation_priority_rank, "allocation_priority_rank")
            if self.allocation_priority_rank == 0:
                raise ValueError("allocation_priority_rank must be positive")
        if self.analytical_qty > 0 and self.pack_multiple is not None:
            if self.rounded_target_qty is None:
                raise ValueError("positive analytical quantity with pack requires rounded target")
            if self.rounded_target_qty % self.pack_multiple:
                raise ValueError("rounded_target_qty must be a whole pack")
        if self.analytical_qty == 0 and (
                self.rounded_target_qty != 0 or self.rounding_delta_qty != 0
                or self.shippable_qty != 0):
            raise ValueError("zero analytical quantity requires zero operational quantities")
        if self.analytical_qty > 0 and self.pack_multiple is None and any(
                value is not None for value in (
                    self.rounded_target_qty, self.rounding_delta_qty, self.shippable_qty)):
            raise ValueError("positive analytical quantity with missing pack must remain unknown")
        if self.rounded_target_qty is not None:
            expected_delta = self.rounded_target_qty - self.analytical_qty
            if expected_delta < 0 or self.rounding_delta_qty != expected_delta:
                raise ValueError("rounding_delta_qty must equal rounded target minus analytical quantity")
        elif self.rounding_delta_qty is not None:
            raise ValueError("rounding_delta_qty requires rounded_target_qty")
        if self.shippable_qty is not None and self.rounded_target_qty is not None:
            if self.shippable_qty > self.rounded_target_qty:
                raise ValueError("shippable_qty cannot exceed rounded_target_qty")
        if self.shippable_qty is not None and self.shippable_qty > 0:
            if self.pack_multiple is None or self.shippable_qty % self.pack_multiple:
                raise ValueError("positive shippable_qty must be a whole pack")
        if self.unit_volume_l is not None:
            if not isinstance(self.unit_volume_l, Decimal):
                raise TypeError("unit_volume_l must be Decimal")
            if not self.unit_volume_l.is_finite() or self.unit_volume_l <= 0:
                raise ValueError("unit_volume_l must be finite and positive")
        if self.total_volume_l is not None:
            if not isinstance(self.total_volume_l, Decimal):
                raise TypeError("total_volume_l must be Decimal")
            if not self.total_volume_l.is_finite() or self.total_volume_l < 0:
                raise ValueError("total_volume_l must be finite and nonnegative")
        expected_volume = (None if self.unit_volume_l is None or self.shippable_qty is None
                           else self.unit_volume_l * self.shippable_qty)
        if self.total_volume_l != expected_volume:
            raise ValueError("total_volume_l must exactly equal unit_volume_l * shippable_qty")
        if not isinstance(self.placement_zone_kind, PlacementZoneKind):
            raise TypeError("placement_zone_kind must be PlacementZoneKind")
        if not isinstance(self.placement_zones, tuple) or any(
                not isinstance(zone, str) or not zone.strip() for zone in self.placement_zones):
            raise TypeError("placement_zones must contain nonblank strings")
        if not isinstance(self.reason_codes, tuple) or any(
                not isinstance(code, str) or not code.strip() for code in self.reason_codes):
            raise TypeError("reason_codes must contain nonblank strings")


@dataclass(frozen=True, slots=True)
class ShippablePlan:
    shippable_plan_id: str
    analysis_snapshot_id: str
    source_mode: SourceMode
    source_snapshot_id: str | None
    analysis_as_of: date
    horizon_days: int
    include_inbound: bool
    objective: AllocationObjective
    lines: tuple[ShippableLine, ...]
    diagnostics: tuple[ShippableDiagnostic, ...]

    def __post_init__(self) -> None:
        _require_nonblank(self.shippable_plan_id, "shippable_plan_id")
        _require_nonblank(self.analysis_snapshot_id, "analysis_snapshot_id")
        if not isinstance(self.source_mode, SourceMode):
            raise TypeError("source_mode must be SourceMode")
        if self.source_mode is SourceMode.API:
            _require_nonblank(self.source_snapshot_id, "source_snapshot_id")
        elif self.source_snapshot_id is not None:
            raise ValueError("FILES source_snapshot_id must be None")
        if type(self.analysis_as_of) is not date:
            raise TypeError("analysis_as_of must be date")
        _require_nonnegative_int(self.horizon_days, "horizon_days")
        if self.horizon_days == 0:
            raise ValueError("horizon_days must be positive")
        if not isinstance(self.include_inbound, bool):
            raise TypeError("include_inbound must be bool")
        if not isinstance(self.objective, AllocationObjective):
            raise TypeError("objective must be AllocationObjective")
        if not isinstance(self.lines, tuple) or any(not isinstance(line, ShippableLine)
                                                    for line in self.lines):
            raise TypeError("lines must contain ShippableLine values")
        if not isinstance(self.diagnostics, tuple) or any(
                not isinstance(item, ShippableDiagnostic) for item in self.diagnostics):
            raise TypeError("diagnostics must contain ShippableDiagnostic values")
        identities = [(line.sku, line.destination_cluster_id) for line in self.lines]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate shippable line identity")
        for sku in {line.sku for line in self.lines}:
            sku_lines = [line for line in self.lines if line.sku == sku]
            stocks = {line.resolved_seller_stock for line in sku_lines}
            if len(stocks) != 1:
                raise ValueError("resolved seller stock must be consistent per SKU")
            shipped = sum(line.shippable_qty or 0 for line in sku_lines)
            if shipped > next(iter(stocks)):
                raise ValueError("shippable quantity exceeds resolved seller stock")
            ranks = [line.allocation_priority_rank for line in sku_lines
                     if line.allocation_priority_rank is not None]
            if len(ranks) != len(set(ranks)) or sorted(ranks) != list(range(1, len(ranks) + 1)):
                raise ValueError("allocation priority ranks must be unique and progressing")
