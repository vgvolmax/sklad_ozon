"""Deterministic and bounded local candidate grouping (no network I/O)."""

from collections import defaultdict
from decimal import Decimal
import hashlib
import json

from backend.ozon.handoff import HandoffPointStore
from backend.supply.contracts import ShippableLine, ShippablePlan

from .contracts import (
    CandidateAssignment,
    CandidateBuildResult,
    CandidateShipment,
    METHOD_RULES,
    ShipmentDiagnostic,
    ShipmentMethod,
    ShipmentScenario,
)
from .handoff import resolve_handoff_points
from .rules import method_cluster_limit, placement_reason
from .seller_warehouse import resolve_seller_warehouse


class ShipmentScopeError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def select_shipment_scope(
    plan: ShippablePlan, selected_cluster_ids: tuple[str, ...],
) -> tuple[ShippableLine, ...]:
    """Filter positive upstream rows; quantities and destinations are untouched."""
    if not isinstance(plan, ShippablePlan):
        raise TypeError("plan must be ShippablePlan")
    selected = set(selected_cluster_ids)
    rows = tuple(line for line in plan.lines
                 if line.destination_cluster_id in selected
                 and line.shippable_qty is not None and line.shippable_qty > 0)
    if not rows:
        raise ShipmentScopeError("EMPTY_SHIPMENT_SCOPE")
    return rows


def _cluster_order(lines: tuple[ShippableLine, ...]) -> tuple[str, ...]:
    grouped = defaultdict(list)
    for line in lines:
        grouped[line.destination_cluster_id].append(line.allocation_priority_rank)
    # A rank is upstream evidence only. Missing evidence falls back to cluster identity.
    def key(cluster_id: str):
        ranks = [rank for rank in grouped[cluster_id] if rank is not None]
        return (min(ranks) if ranks else 2**63, cluster_id)
    return tuple(sorted(grouped, key=key))


def _groups(
    clusters: tuple[str, ...], lines_by_cluster: dict[str, tuple[ShippableLine, ...]],
    size: int, volume_limit: Decimal | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Linear greedy grouping; an indivisible over-limit cluster is blocked."""
    result: list[tuple[str, ...]] = []
    blocked: list[str] = []
    current: list[str] = []
    current_volume = Decimal("0")
    for cluster in clusters:
        volume = sum((line.total_volume_l or Decimal("0")
                      for line in lines_by_cluster[cluster]), Decimal("0"))
        if volume_limit is not None and volume > volume_limit:
            if current:
                result.append(tuple(current)); current = []; current_volume = Decimal("0")
            blocked.append(cluster)
            continue
        if current and (len(current) >= size or (
                volume_limit is not None and current_volume + volume > volume_limit)):
            result.append(tuple(current)); current = []; current_volume = Decimal("0")
        current.append(cluster)
        current_volume += volume
    if current:
        result.append(tuple(current))
    return tuple(result), tuple(blocked)


def _assignment(line: ShippableLine) -> CandidateAssignment:
    # Candidate eligibility guarantees these upstream operational prerequisites.
    assert line.shippable_qty is not None
    assert line.pack_multiple is not None
    assert line.unit_volume_l is not None
    assert line.total_volume_l is not None
    return CandidateAssignment(
        line.sku, line.article, line.destination_cluster_id, line.shippable_qty,
        line.pack_multiple, line.unit_volume_l, line.total_volume_l,
        line.placement_zone_kind.value, line.placement_zones,
    )


def _scenario_payload(scenario: ShipmentScenario) -> dict[str, object]:
    return {
        "selected_cluster_ids": scenario.selected_cluster_ids,
        "date_from": scenario.date_from.isoformat(), "date_to": scenario.date_to.isoformat(),
        "allowed_methods": tuple(item.value for item in scenario.allowed_methods),
        "preferred_clusters_per_shipment": scenario.preferred_clusters_per_shipment,
        "max_clusters_per_shipment": scenario.max_clusters_per_shipment,
        "seller_warehouse_id": scenario.seller_warehouse_id,
        "selected_handoff_point_ids": scenario.selected_handoff_point_ids,
    }


def _candidate_id(plan, scenario, method, seller_id, handoff_id, clusters, assignments):
    payload = {
        "shippable_plan_id": plan.shippable_plan_id,
        "analysis_snapshot_id": plan.analysis_snapshot_id,
        "scenario": _scenario_payload(scenario), "method": method.value,
        "seller_warehouse_id": seller_id, "handoff_point_id": handoff_id,
        "cluster_ids": clusters,
        "assignments": tuple((item.sku, item.destination_cluster_id, item.quantity)
                             for item in assignments),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode()
    return "cs_" + hashlib.sha256(canonical).hexdigest()


def build_candidate_result(
    *, plan: ShippablePlan, scenario: ShipmentScenario, seller_warehouses,
    handoff_store: HandoffPointStore, max_candidates: int = 12,
) -> CandidateBuildResult:
    if not isinstance(plan, ShippablePlan) or not isinstance(scenario, ShipmentScenario):
        raise TypeError("plan and scenario must use shipment contracts")
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int):
        raise TypeError("max_candidates must be an int")
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")
    try:
        scope = select_shipment_scope(plan, scenario.selected_cluster_ids)
    except ShipmentScopeError as exc:
        return CandidateBuildResult((), (ShipmentDiagnostic(exc.code),))

    diagnostics: list[ShipmentDiagnostic] = []
    candidates: list[CandidateShipment] = []
    seller_warehouses = tuple(seller_warehouses)
    lines_by_cluster = {
        cluster: tuple(line for line in scope if line.destination_cluster_id == cluster)
        for cluster in _cluster_order(scope)
    }
    clusters = tuple(lines_by_cluster)
    for method in scenario.allowed_methods:
        if len(candidates) >= max_candidates:
            break
        rule = METHOD_RULES[method]
        warehouse = resolve_seller_warehouse(
            seller_warehouses, scenario.seller_warehouse_id,
            required=rule.requires_seller_warehouse)
        if warehouse.reason_code:
            diagnostics.append(ShipmentDiagnostic(warehouse.reason_code, method)); continue
        handoffs = resolve_handoff_points(
            handoff_store, scenario.selected_handoff_point_ids,
            required=rule.requires_handoff_point)
        if handoffs.reason_code:
            diagnostics.append(ShipmentDiagnostic(handoffs.reason_code, method)); continue
        valid_clusters = []
        for cluster in clusters:
            reasons = {placement_reason(line, method) for line in lines_by_cluster[cluster]}
            if any(line.unit_volume_l is None or line.total_volume_l is None
                   for line in lines_by_cluster[cluster]):
                reasons.add("MISSING_UNIT_VOLUME")
            reasons.discard(None)
            if reasons:
                diagnostics.extend(ShipmentDiagnostic(code, method, cluster)
                                   for code in sorted(reasons))
            else:
                valid_clusters.append(cluster)
        size = min(scenario.preferred_clusters_per_shipment,
                   method_cluster_limit(method, scenario.max_clusters_per_shipment))
        groups, blocked = _groups(tuple(valid_clusters), lines_by_cluster, size,
                                  rule.preliminary_max_shipment_item_volume_l)
        diagnostics.extend(ShipmentDiagnostic(
            "PVZ_PRELIMINARY_VOLUME_LIMIT", method, cluster) for cluster in blocked)
        destinations = handoffs.points if rule.requires_handoff_point else (None,)
        for point in destinations:
            for group in groups:
                if len(candidates) >= max_candidates:
                    break
                assignments = tuple(sorted(
                    (_assignment(line) for cluster in group for line in lines_by_cluster[cluster]),
                    key=lambda item: (item.destination_cluster_id, item.sku)))
                total_qty = sum(item.quantity for item in assignments)
                total_volume = sum((item.total_volume_l for item in assignments), Decimal("0"))
                seller_id = (None if warehouse.warehouse is None else
                             warehouse.warehouse.seller_warehouse_id)
                point_id = None if point is None else point.warehouse_id
                point_type = None if point is None else point.warehouse_type
                candidates.append(CandidateShipment(
                    _candidate_id(plan, scenario, method, seller_id, point_id,
                                  group, assignments), method, seller_id, point_id,
                    point_type, group, assignments, total_qty, total_volume, ()))
    # Preserve causal discovery order while suppressing repeated equivalent diagnostics.
    return CandidateBuildResult(tuple(candidates), tuple(dict.fromkeys(diagnostics)))


def build_candidate_shipments(**kwargs) -> tuple[CandidateShipment, ...]:
    return build_candidate_result(**kwargs).candidates
