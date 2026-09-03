"""Public independent demand-need decision API."""

from .contracts import (AnalysisSnapshot, DecisionRow, DecisionSummary, DiagnosticView,
                        FlowEconomicsAggregate, FlowLinkView, FlowView, FlowViewAggregates, HorizonComparability,
                        InputStatusView, NeedComparison, RouteSkuBreakdown, ScenarioSettings)
from .need import calculate_need, forecast_horizon
from .snapshot import assemble_snapshot

__all__ = (
    "HorizonComparability",
    "NeedComparison",
    "ScenarioSettings",
    "AnalysisSnapshot", "DecisionRow", "DecisionSummary", "DiagnosticView",
    "FlowEconomicsAggregate", "FlowLinkView", "FlowView", "FlowViewAggregates", "InputStatusView",
    "RouteSkuBreakdown", "assemble_snapshot",
    "calculate_need",
    "forecast_horizon",
)
