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
from .route_opportunity import RouteOpportunity, calculate_route_opportunity

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
    "calculate_route_opportunity",
)
