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
    OperationalSupplyFact,
    PlacementZoneKind,
    PhysicalFeasibilityState,
    RestrictionEligibility,
    ShippableDiagnostic,
    ShippableLine,
    ShippablePlan,
    SupplyProductIdentity,
    SupplyFeasibility,
    WarehouseCapability,
)
from .feasibility import assess_feasibility
from .optimizer import optimize_allocations
from .placement import compare_placements
from .shippable_plan import build_shippable_plan, round_up_to_pack
from backend.domain.contracts import RestrictionCapacityKind

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
    "OperationalSupplyFact", "PlacementZoneKind", "PhysicalFeasibilityState", "RestrictionEligibility",
    "RestrictionCapacityKind", "SupplyProductIdentity",
    "ShippableDiagnostic", "ShippableLine", "ShippablePlan",
    "assess_feasibility",
    "compare_placements",
    "optimize_allocations",
    "build_shippable_plan", "round_up_to_pack",
)
