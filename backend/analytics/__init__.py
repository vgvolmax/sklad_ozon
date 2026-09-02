"""Pure demand and fulfilled-route analytics."""

from ._weeks import AnalyticsWindow, WeekPolicy
from .demand import DemandCell, DemandResult, aggregate_demand
from .demand_estimate import DemandEstimate, DemandRegime, estimate_destination_demand
from .routes import RouteCell, RouteProfile, build_route_profile
from .route_profiles import RouteProfileSelection, select_route_profile
from .flows import FulfillmentFlowCell, aggregate_clean_flows, aggregate_observed_flows
from .stockout import StockoutThresholds, detect_stockouts
from .distortion import detect_recommendation_distortion
from .clean_routes import (
    CleanRouteFallbackStatus,
    CleanRoutePolicy,
    CleanRouteResult,
    ExcludedRouteEvidence,
    RouteDistributionCell,
    RouteProfileSummary,
    build_clean_route_profile,
)

__all__ = (
    "AnalyticsWindow",
    "CleanRouteFallbackStatus",
    "CleanRoutePolicy",
    "CleanRouteResult",
    "DemandCell",
    "DemandResult",
    "DemandEstimate",
    "DemandRegime",
    "ExcludedRouteEvidence",
    "FulfillmentFlowCell",
    "RouteCell",
    "RouteDistributionCell",
    "RouteProfile",
    "RouteProfileSelection",
    "RouteProfileSummary",
    "WeekPolicy",
    "aggregate_demand",
    "aggregate_clean_flows",
    "aggregate_observed_flows",
    "build_route_profile",
    "build_clean_route_profile",
    "detect_recommendation_distortion",
    "detect_stockouts",
    "estimate_destination_demand",
    "select_route_profile",
    "StockoutThresholds",
)
