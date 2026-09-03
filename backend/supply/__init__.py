"""Public supply feasibility and placement assessment API."""

from .contracts import (
    AllocationDecision,
    AllocationObjective,
    OptimizationResult,
    PlacementAssessment,
    PlacementInput,
    PlacementSource,
    PlanFamily,
    RouteConfidence,
    SupplyFeasibility,
    WarehouseCapability,
)
from .feasibility import assess_feasibility
from .optimizer import optimize_allocations
from .placement import compare_placements

__all__ = (
    "PlacementSource",
    "PlanFamily",
    "AllocationObjective",
    "RouteConfidence",
    "WarehouseCapability",
    "SupplyFeasibility",
    "PlacementInput",
    "PlacementAssessment",
    "AllocationDecision",
    "OptimizationResult",
    "assess_feasibility",
    "compare_placements",
    "optimize_allocations",
)
