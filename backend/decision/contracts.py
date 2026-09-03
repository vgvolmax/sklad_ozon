"""Immutable contracts for independent demand-need decisions."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from backend.supply.contracts import AllocationObjective
from backend.analytics.clean_routes import CleanRouteResult
from backend.analytics.demand_estimate import DemandEstimate
from backend.analytics.routes import RouteProfile
from backend.domain.contracts import ReportMeta
from backend.domain.signals import RecommendationDistortionSignal, SignalConfidence, StockoutSignal
from backend.economics import RouteOpportunity, UnitEconomicsResult
from backend.supply.contracts import OptimizationResult


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


@dataclass(frozen=True, slots=True)
class DiagnosticView:
    severity: str
    code: str
    message: str
    sku: str | None = None
    cluster_id: str | None = None
    destination_cluster_id: str | None = None


@dataclass(frozen=True, slots=True)
class InputStatusView:
    ok: bool
    record_count: int
    diagnostics: tuple[DiagnosticView, ...]


@dataclass(frozen=True, slots=True)
class DecisionSummary:
    sku_count: int
    decision_row_count: int
    total_ozon_recommended_qty: int
    total_calculated_need_qty: int
    total_safe_plan_qty: int
    total_calculated_plan_qty: int
    expected_calculated_plan_profit: Decimal
    disagreement_row_count: int
    incomplete_row_count: int


@dataclass(frozen=True, slots=True)
class RouteSkuBreakdown:
    sku: str; article: str; product_name: str; quantity: int
    route_share: Decimal; destination_demand_share: Decimal
    margin_delta_pp: Decimal | None
    observed_profit_opportunity_rub: Decimal | None
    profit_opportunity_rub: Decimal | None


@dataclass(frozen=True, slots=True)
class FlowEconomicsAggregate:
    """UI-ready economics for one evidence-weighted flow group."""
    quantity: int
    route_cost_rub_per_unit: Decimal | None
    route_cost_pct_of_realization: Decimal | None
    current_margin_rate: Decimal | None
    local_route_cost_rub_per_unit: Decimal | None
    local_route_cost_pct_of_realization: Decimal | None
    local_margin_rate: Decimal | None
    margin_delta_pp: Decimal | None
    profit_delta_per_unit: Decimal | None
    profit_opportunity_rub: Decimal | None
    complete: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlowLinkView:
    origin_cluster_id: str; destination_cluster_id: str; quantity: int
    destination_share: Decimal
    margin_delta_pp: Decimal | None
    observed_profit_opportunity_rub: Decimal | None
    route_economics_complete: bool
    route_reason_codes: tuple[str, ...]
    sku_breakdown: tuple[RouteSkuBreakdown, ...]
    economics: FlowEconomicsAggregate


@dataclass(frozen=True, slots=True)
class FlowView:
    mode: str; key: str; evidence_source: str; total_quantity: int
    local_share: Decimal | None; external_share: Decimal | None; donor_count: int
    external_economics: FlowEconomicsAggregate | None
    links: tuple[FlowLinkView, ...]

    def __post_init__(self) -> None:
        if self.mode not in {"destination", "origin", "sku"}:
            raise ValueError("mode must be destination, origin, or sku")
        if self.evidence_source not in {"observed", "clean"}:
            raise ValueError("evidence_source must be observed or clean")


@dataclass(frozen=True, slots=True)
class FlowViewAggregates:
    observed_views: tuple[FlowView, ...]
    clean_views: tuple[FlowView, ...]


@dataclass(frozen=True, slots=True)
class DecisionRow:
    sku: str; article: str; product_name: str; destination_cluster_id: str
    demand: DemandEstimate | None; need: NeedComparison
    safe_plan_qty: int | None; calculated_plan_qty: int | None
    current_fbo_stock: int | None; inbound_qty: int | None
    route_external_share: Decimal | None
    route_margin_opportunity_pp: Decimal | None
    observed_profit_opportunity_rub: Decimal | None
    expected_plan_profit: Decimal | None
    confidence: SignalConfidence
    status_codes: tuple[str, ...]; explanations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    snapshot_id: str; created_at: str
    report_meta: dict[str, ReportMeta]
    freshness_warnings: tuple[str, ...]
    scenario: ScenarioSettings
    input_statuses: dict[str, InputStatusView]
    summary: DecisionSummary
    decision_rows: tuple[DecisionRow, ...]
    demand_estimates: tuple[DemandEstimate, ...]
    observed_routes: RouteProfile
    clean_routes: CleanRouteResult
    stockout_signals: tuple[StockoutSignal, ...]
    distortion_signals: tuple[RecommendationDistortionSignal, ...]
    route_economics: tuple[RouteOpportunity, ...]
    unit_economics: tuple[UnitEconomicsResult, ...]
    safe_allocations: tuple[OptimizationResult, ...]
    calculated_allocations: tuple[OptimizationResult, ...]
    flow_view_aggregates: FlowViewAggregates
    diagnostics: tuple[DiagnosticView, ...]
