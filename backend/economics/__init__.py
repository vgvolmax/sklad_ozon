"""Public contracts for tariff-based economics calculations."""

from .tariffs import (
    ExpectedLogisticsResult,
    LogisticsContext,
    LogisticsCoverageStatus,
    LogisticsDiagnostic,
    RouteLogisticsContribution,
    RouteProfileSource,
    TariffLookupStatus,
    expected_logistics,
)
from .unit import (
    CalculationBases,
    EconomicsLineItem,
    RoundingMetadata,
    UnitEconomicsResult,
    calculate_unit_economics,
)
from .route_opportunity import (RouteCounterfactual, RouteOpportunity,
                                calculate_route_counterfactual,
                                calculate_route_opportunity)
from .stockout_impact import (ImpactEconomicsAggregate, RouteDayQuantityImpact,
    RouteQuantityImpact, StockoutEpisodeImpact, aggregate_impacts,
    apply_route_quantity, build_stockout_episode_impacts,
    deduplicate_route_day_impacts)

__all__ = (
    "ExpectedLogisticsResult",
    "LogisticsContext",
    "LogisticsCoverageStatus",
    "LogisticsDiagnostic",
    "RouteLogisticsContribution",
    "RouteProfileSource",
    "TariffLookupStatus",
    "expected_logistics",
    "CalculationBases",
    "EconomicsLineItem",
    "RoundingMetadata",
    "UnitEconomicsResult",
    "calculate_unit_economics",
    "RouteOpportunity",
    "RouteCounterfactual",
    "calculate_route_counterfactual",
    "calculate_route_opportunity",
    "ImpactEconomicsAggregate", "RouteDayQuantityImpact", "RouteQuantityImpact",
    "StockoutEpisodeImpact", "aggregate_impacts", "apply_route_quantity",
    "build_stockout_episode_impacts", "deduplicate_route_day_impacts",
)
