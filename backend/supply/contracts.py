"""Immutable contracts for supply feasibility and placement assessment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from backend.domain.signals import RecommendationDistortionSignal

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
    allowed: bool
    max_supply_qty: int | None
    eligible_warehouses: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlacementInput:
    sku: str
    cluster_id: str
    ozon_recommended_qty: int
    sources: tuple[PlacementSource, ...]
    economics: UnitEconomicsResult
    distortion_signal: RecommendationDistortionSignal | None
    route_confidence: RouteConfidence
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
