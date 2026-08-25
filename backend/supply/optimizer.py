"""Deterministic bounded allocation for one SKU's placement assessments."""

from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from backend.domain.signals import SignalConfidence
from backend.project import OptimizerThresholds

from .contracts import (
    AllocationDecision,
    OptimizationResult,
    PlacementAssessment,
    RouteConfidence,
)


_ZERO = Decimal("0")
_ROUTE_RANK = {RouteConfidence.LOW: 1, RouteConfidence.MEDIUM: 2, RouteConfidence.HIGH: 3}
_DISTORTION_RANK = {
    None: 0,
    SignalConfidence.LOW: 1,
    SignalConfidence.MEDIUM: 2,
    SignalConfidence.HIGH: 3,
}
_REASON_ORDER = (
    "PHYSICALLY_INFEASIBLE",
    "PHYSICAL_CEILING_ZERO",
    "OZON_RECOMMENDATION_CEILING_ZERO",
    "ECONOMICS_INCOMPLETE",
    "MARGIN_RATE_UNAVAILABLE",
    "ROI_UNAVAILABLE",
    "NON_POSITIVE_PROFIT",
    "BELOW_MIN_PROFIT_PER_UNIT",
    "BELOW_MIN_MARGIN_RATE",
    "BELOW_MIN_ROI",
    "ELIGIBLE_FOR_ALLOCATION",
    "SELLER_STOCK_EXHAUSTED",
    "PARTIAL_BY_SELLER_STOCK",
    "ALLOCATED",
)


def _validate_thresholds(thresholds: object) -> OptimizerThresholds:
    if not isinstance(thresholds, OptimizerThresholds):
        raise TypeError("thresholds must be OptimizerThresholds")
    for name in OptimizerThresholds.__slots__:
        value = getattr(thresholds, name)
        if not isinstance(value, Decimal):
            raise TypeError(f"thresholds.{name} must be Decimal")
        if not value.is_finite():
            raise ValueError(f"thresholds.{name} must be finite")
    return thresholds


def _ceiling(candidate: PlacementAssessment) -> int:
    if not candidate.feasibility.allowed:
        return 0
    physical = candidate.feasibility.max_supply_qty
    if physical is None:
        return candidate.ozon_recommended_qty
    return min(candidate.ozon_recommended_qty, physical)


def _classify(candidate: PlacementAssessment, ceiling: int,
              thresholds: OptimizerThresholds) -> tuple[bool, set[str]]:
    reasons: set[str] = set()
    if not candidate.feasibility.allowed:
        reasons.add("PHYSICALLY_INFEASIBLE")
    elif candidate.feasibility.max_supply_qty == 0:
        reasons.add("PHYSICAL_CEILING_ZERO")
    if candidate.ozon_recommended_qty == 0:
        reasons.add("OZON_RECOMMENDATION_CEILING_ZERO")

    economics = candidate.economics
    if not economics.complete:
        reasons.add("ECONOMICS_INCOMPLETE")
    else:
        profit = economics.profit_per_unit
        margin = economics.margin_rate
        roi = economics.roi
        if margin is None:
            reasons.add("MARGIN_RATE_UNAVAILABLE")
        if roi is None:
            reasons.add("ROI_UNAVAILABLE")
        if profit is None or profit <= _ZERO:
            reasons.add("NON_POSITIVE_PROFIT")
        if profit is not None and profit < thresholds.min_profit_per_unit:
            reasons.add("BELOW_MIN_PROFIT_PER_UNIT")
        if margin is not None and margin < thresholds.min_margin_rate:
            reasons.add("BELOW_MIN_MARGIN_RATE")
        if roi is not None and roi < thresholds.min_roi:
            reasons.add("BELOW_MIN_ROI")

    eligible = not reasons and ceiling > 0
    if eligible:
        reasons.add("ELIGIBLE_FOR_ALLOCATION")
    return eligible, reasons


def _ordered(reasons: set[str]) -> tuple[str, ...]:
    return tuple(reason for reason in _REASON_ORDER if reason in reasons)


def optimize_allocations(
    candidates: Iterable[PlacementAssessment],
    available_stock: int,
    thresholds: OptimizerThresholds,
) -> OptimizationResult:
    """Maximize absolute profit under recommendation, physical, and stock ceilings."""
    if isinstance(available_stock, bool) or not isinstance(available_stock, int):
        raise TypeError("available_stock must be an int")
    if available_stock < 0:
        raise ValueError("available_stock must be nonnegative")
    thresholds = _validate_thresholds(thresholds)
    items = tuple(candidates)
    if not items:
        raise ValueError("candidates must not be empty")
    for item in items:
        if not isinstance(item, PlacementAssessment):
            raise TypeError("candidates must contain PlacementAssessment values")
    sku = items[0].sku
    if any(item.sku != sku for item in items):
        raise ValueError("all candidates must have the same SKU")
    keys = [(item.sku, item.cluster_id) for item in items]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate SKU and cluster candidate")

    ceilings = {item.cluster_id: _ceiling(item) for item in items}
    classified = {
        item.cluster_id: _classify(item, ceilings[item.cluster_id], thresholds)
        for item in items
    }
    eligible = [item for item in items if classified[item.cluster_id][0]]
    # Stable least-significant-first sorts avoid doing arithmetic on Decimal keys.
    eligible.sort(key=lambda item: item.cluster_id)
    eligible.sort(key=lambda item: item.ozon_recommended_qty, reverse=True)
    eligible.sort(key=lambda item: _DISTORTION_RANK[
        None if item.distortion_signal is None else item.distortion_signal.confidence])
    eligible.sort(key=lambda item: _ROUTE_RANK[item.route_confidence], reverse=True)
    eligible.sort(key=lambda item: item.economics.profit_per_unit, reverse=True)

    remaining = available_stock
    quantities: dict[str, int] = {}
    for item in eligible:
        quantity = min(remaining, ceilings[item.cluster_id])
        quantities[item.cluster_id] = quantity
        remaining -= quantity

    decisions: list[AllocationDecision] = []
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_EVEN
        for item in sorted(items, key=lambda candidate: candidate.cluster_id):
            eligible_item, reasons = classified[item.cluster_id]
            quantity = quantities.get(item.cluster_id, 0)
            ceiling = ceilings[item.cluster_id]
            if eligible_item and quantity == 0 and available_stock > 0:
                reasons.add("SELLER_STOCK_EXHAUSTED")
            if 0 < quantity < ceiling:
                reasons.add("PARTIAL_BY_SELLER_STOCK")
            if quantity > 0:
                reasons.add("ALLOCATED")
            profit_per_unit = item.economics.profit_per_unit
            expected_profit = _ZERO if profit_per_unit is None else quantity * profit_per_unit
            decisions.append(AllocationDecision(
                sku, item.cluster_id, quantity, ceiling, profit_per_unit,
                expected_profit, eligible_item, _ordered(reasons),
            ))
        eligible_capacity = sum(ceilings[item.cluster_id] for item in eligible)
        allocated = sum(decision.allocation_qty for decision in decisions)
        objective = sum((decision.expected_profit for decision in decisions), _ZERO)

    if eligible_capacity == 0:
        binding = (("ZERO_AVAILABLE_STOCK", "NO_ELIGIBLE_CAPACITY")
                   if available_stock == 0 else ("NO_ELIGIBLE_CAPACITY",))
    elif available_stock == 0:
        binding = ("ZERO_AVAILABLE_STOCK", "SELLER_STOCK_LIMIT")
    elif available_stock < eligible_capacity:
        binding = ("SELLER_STOCK_LIMIT",)
    elif available_stock > eligible_capacity:
        binding = ("CANDIDATE_CEILINGS_LIMIT",)
    else:
        binding = ("SELLER_STOCK_EQUALS_CANDIDATE_CEILINGS",)

    return OptimizationResult(
        sku, available_stock, allocated, available_stock - allocated,
        eligible_capacity, objective, tuple(decisions), binding,
    )
