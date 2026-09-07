"""Public independent demand-need decision API."""

from .contracts import (AnalysisSnapshot, DataQualityAffectedEntity, DataQualityIssueGroup,
                        DataQualityLevel, DataQualityPresentation, DecisionRow, DecisionSummary, DiagnosticView,
                        FlowContextSummary, FlowEconomicsAggregate, FlowLinkView,
                        FlowMetricOverview, FlowView, FlowViewAggregates, HorizonComparability,
                        ImpactEconomicsView, RouteImpactView, EpisodeDonorBreakdown,
                        EpisodeSkuBreakdown, StockoutEpisodeView, DestinationDailyPoint,
                        DestinationDailySeries, DestinationImpactSummary,
                        StockoutImpactPresentation, InputStatusView, NeedComparison,
                        RouteSkuBreakdown, ScenarioSettings)
from .need import calculate_need, forecast_horizon
from .snapshot import assemble_snapshot
from .impact import ECONOMICS_BASIS_TEXT, build_stockout_impact_presentation
from .data_quality import (DataQualityFact, build_data_quality_presentation,
    build_stockout_tariff_quality_facts, classify_product_economics_gap,
    classify_tariff_gap, tariff_gap_user_detail)

__all__ = (
    "HorizonComparability",
    "DataQualityLevel", "DataQualityAffectedEntity", "DataQualityIssueGroup",
    "DataQualityPresentation", "DataQualityFact", "build_data_quality_presentation",
    "classify_tariff_gap", "build_stockout_tariff_quality_facts",
    "classify_product_economics_gap", "tariff_gap_user_detail",
    "NeedComparison",
    "ScenarioSettings",
    "AnalysisSnapshot", "DecisionRow", "DecisionSummary", "DiagnosticView",
    "FlowContextSummary", "FlowEconomicsAggregate", "FlowLinkView",
    "FlowMetricOverview", "FlowView", "FlowViewAggregates", "InputStatusView",
    "ImpactEconomicsView", "RouteImpactView", "EpisodeDonorBreakdown",
    "EpisodeSkuBreakdown", "StockoutEpisodeView", "DestinationDailyPoint",
    "DestinationDailySeries", "DestinationImpactSummary", "StockoutImpactPresentation",
    "RouteSkuBreakdown", "assemble_snapshot",
    "ECONOMICS_BASIS_TEXT", "build_stockout_impact_presentation",
    "calculate_need",
    "forecast_horizon",
)
