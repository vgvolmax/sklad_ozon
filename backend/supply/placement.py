"""Counterfactual placement comparison without allocation decisions."""

from collections.abc import Iterable

from backend.ingestion.restrictions import RestrictionRecord

from .contracts import PlacementAssessment, PlacementInput, PlacementSource, WarehouseCapability
from .feasibility import assess_feasibility


def compare_placements(
    candidates: Iterable[PlacementInput],
    restrictions: Iterable[RestrictionRecord],
    warehouses: Iterable[WarehouseCapability],
) -> tuple[PlacementAssessment, ...]:
    """Return visible, deterministic assessments while preserving supplied economics."""
    candidate_items = tuple(candidates)
    restriction_items = tuple(restrictions)
    warehouse_items = tuple(warehouses)
    seen: set[tuple[str, str]] = set()
    assessments: list[PlacementAssessment] = []

    for candidate in candidate_items:
        if not isinstance(candidate, PlacementInput):
            raise TypeError("candidates must contain PlacementInput values")
        key = candidate.sku, candidate.cluster_id
        if key in seen:
            raise ValueError(f"Duplicate candidate for SKU and cluster: {key!r}")
        seen.add(key)
        feasibility = assess_feasibility(
            candidate.sku, candidate.cluster_id, restriction_items, warehouse_items)
        source_set = set(candidate.sources)
        statuses = tuple(code for condition, code in (
            (PlacementSource.OBSERVED in source_set, "OBSERVED_CANDIDATE"),
            (PlacementSource.RECOMMENDED in source_set, "RECOMMENDED_CANDIDATE"),
            (PlacementSource.COUNTERFACTUAL in source_set, "COUNTERFACTUAL_CANDIDATE"),
            (not feasibility.allowed, "PHYSICALLY_INFEASIBLE"),
            (feasibility.max_supply_qty == 0, "PHYSICAL_CEILING_ZERO"),
            (not candidate.economics.complete, "ECONOMICS_INCOMPLETE"),
            (candidate.ozon_recommended_qty == 0, "AUTOMATIC_CEILING_ZERO"),
            (candidate.distortion_signal is not None, "RECOMMENDATION_DISTORTION_SIGNAL"),
        ) if condition)
        assessments.append(PlacementAssessment(
            candidate.sku, candidate.cluster_id, candidate.ozon_recommended_qty,
            feasibility, candidate.economics, candidate.distortion_signal,
            candidate.route_confidence, statuses,
        ))

    return tuple(sorted(assessments, key=lambda item: (item.sku, item.cluster_id)))
