"""Pure demand and fulfilled-route analytics."""

from ._weeks import AnalyticsWindow, WeekPolicy
from .daily import (
    DailyDemandCell,
    DailyDemandResult,
    DailyFulfillmentCell,
    DailyFulfillmentResult,
    DailyOrderFacts,
    build_daily_order_facts,
)
from .demand import DemandCell, DemandResult, aggregate_demand, aggregate_weekly_demand
from .demand_estimate import DemandEstimate, DemandRegime, estimate_destination_demand
from .routes import RouteCell, RouteProfile, build_route_profile, build_weekly_route_profile
from .route_profiles import RouteProfileSelection, select_route_profile
from .flows import FulfillmentFlowCell, aggregate_clean_flows, aggregate_observed_flows
from .stockout import StockoutThresholds, detect_stockouts
from .distortion import detect_recommendation_distortion
from .stockout_episodes import (
    DailyLocalityPoint, DailyOriginShare, DailyStockoutThresholds,
    EpisodeReplacementOriginEvidence, StockoutEpisode, StockoutEpisodeScope,
    build_daily_locality_series, detect_stockout_episodes,
)
from .clean_routes import (
    CleanRouteFallbackStatus,
    CleanRoutePolicy,
    CleanRouteResult,
    EpisodeExcludedRouteEvidence,
    ExcludedRouteEvidence,
    RouteDistributionCell,
    RouteProfileSummary,
    build_clean_route_profile,
    build_episode_clean_route_profile,
)

__all__ = (
    "AnalyticsWindow",
    "detect_stockout_episodes",
    "build_episode_clean_route_profile",
    "build_daily_locality_series",
    "StockoutEpisodeScope",
    "StockoutEpisode",
    "EpisodeReplacementOriginEvidence",
    "EpisodeExcludedRouteEvidence",
    "DailyStockoutThresholds",
    "DailyOriginShare",
    "DailyLocalityPoint",
    "CleanRouteFallbackStatus",
    "CleanRoutePolicy",
    "CleanRouteResult",
    "DemandCell",
    "DemandResult",
    "DailyDemandCell",
    "DailyDemandResult",
    "DailyFulfillmentCell",
    "DailyFulfillmentResult",
    "DailyOrderFacts",
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
    "aggregate_weekly_demand",
    "aggregate_clean_flows",
    "aggregate_observed_flows",
    "build_route_profile",
    "build_weekly_route_profile",
    "build_daily_order_facts",
    "build_clean_route_profile",
    "detect_recommendation_distortion",
    "detect_stockouts",
    "estimate_destination_demand",
    "select_route_profile",
    "StockoutThresholds",
)
