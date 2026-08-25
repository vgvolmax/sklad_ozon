"""Immutable contracts for supply feasibility and placement assessment."""

from dataclasses import dataclass
from enum import Enum

from backend.domain.signals import RecommendationDistortionSignal
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

    def __post_init__(self) -> None:
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
