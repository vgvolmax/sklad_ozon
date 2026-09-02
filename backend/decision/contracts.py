"""Immutable contracts for independent demand-need decisions."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from backend.supply.contracts import AllocationObjective


class HorizonComparability(str, Enum):
    SAME_HORIZON = "same_horizon"
    DIFFERENT_HORIZON = "different_horizon"
    OZON_HORIZON_UNKNOWN = "ozon_horizon_unknown"
    OZON_RECOMMENDATION_MISSING = "ozon_recommendation_missing"


@dataclass(frozen=True, slots=True)
class ScenarioSettings:
    horizon_days: int
    include_inbound: bool
    objective: AllocationObjective

    def __post_init__(self) -> None:
        if isinstance(self.horizon_days, bool) or not isinstance(self.horizon_days, int):
            raise TypeError("horizon_days must be an int")
        if self.horizon_days <= 0:
            raise ValueError("horizon_days must be positive")
        if not isinstance(self.include_inbound, bool):
            raise TypeError("include_inbound must be a bool")
        if not isinstance(self.objective, AllocationObjective):
            raise TypeError("objective must be an AllocationObjective")


@dataclass(frozen=True, slots=True)
class NeedComparison:
    sku: str
    destination_cluster_id: str
    current_weekly_rate: Decimal | None
    horizon_days: int
    raw_demand_forecast: Decimal | None
    current_fbo_stock: int | None
    inbound_qty: int | None
    inbound_included: bool
    calculated_need_qty: int | None
    ozon_recommended_qty: int | None
    ozon_horizon_days: int | None
    delta_qty: int | None
    delta_pct: Decimal | None
    comparability: HorizonComparability
    complete: bool
    blocker_codes: tuple[str, ...]
