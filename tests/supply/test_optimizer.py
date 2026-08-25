"""PR7 Task 16 deterministic stock optimization behavior."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, ROUND_HALF_EVEN, getcontext, localcontext
from itertools import permutations

import pytest

from backend.domain.signals import RecommendationDistortionSignal, SignalConfidence
from backend.economics import CalculationBases, RoundingMetadata, UnitEconomicsResult
from backend.project import OptimizerThresholds
from backend.supply import (
    AllocationDecision,
    OptimizationResult,
    PlacementAssessment,
    RouteConfidence,
    SupplyFeasibility,
    optimize_allocations,
)


def thresholds(profit="10", margin="0.10", roi="0.20"):
    return OptimizerThresholds(Decimal(profit), Decimal(margin), Decimal(roi))


def candidate(cluster="A", *, sku="SKU-1", recommendation=10, physical=None,
              allowed=True, complete=True, profit="30", margin="0.30", roi="0.40",
              route=RouteConfidence.MEDIUM, distortion=None):
    economics = UnitEconomicsResult(
        sku, cluster, Decimal("100"), Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("0"), None if profit is None else Decimal(profit),
        None if margin is None else Decimal(margin), None if roi is None else Decimal(roi),
        complete, () if complete else ("fixture",), CalculationBases(), (), RoundingMetadata(),
    )
    feasibility = SupplyFeasibility(
        sku, cluster, allowed, physical, ("W",) if allowed else (), ("fixture",),
    )
    return PlacementAssessment(
        sku, cluster, recommendation, feasibility, economics, distortion, route, (),
    )


def allocations(result):
    return {decision.cluster_id: decision.allocation_qty for decision in result.decisions}


def test_basic_greedy_is_bounded_and_reconciles_objective():
    result = optimize_allocations([
        candidate("B", recommendation=10, profit="20"),
        candidate("A", recommendation=4, profit="30"),
    ], 6, thresholds())
    assert allocations(result) == {"A": 4, "B": 2}
    assert result.allocated_qty == 6
    assert result.objective_profit == Decimal("160")
    assert result.objective_profit == sum((item.expected_profit for item in result.decisions), Decimal("0"))
    assert result.binding_reasons == ("SELLER_STOCK_LIMIT",)
    assert result.decisions[1].reason_codes == (
        "ELIGIBLE_FOR_ALLOCATION", "PARTIAL_BY_SELLER_STOCK", "ALLOCATED")


@pytest.mark.parametrize("item,stock,ceiling", [
    (candidate(recommendation=3), 100, 3),
    (candidate(recommendation=10, physical=2), 100, 2),
])
def test_recommendation_and_physical_caps_are_hard_ceiling(item, stock, ceiling):
    result = optimize_allocations([item], stock, thresholds())
    assert allocations(result) == {"A": ceiling}
    assert result.decisions[0].automatic_ceiling_qty == ceiling
    assert result.unallocated_stock == stock - ceiling
    assert result.binding_reasons == ("CANDIDATE_CEILINGS_LIMIT",)


@pytest.mark.parametrize("item,ceiling,reasons", [
    (candidate(recommendation=0, profit="1000", route=RouteConfidence.HIGH),
     0, ("OZON_RECOMMENDATION_CEILING_ZERO",)),
    (candidate(recommendation=100, physical=0), 0, ("PHYSICAL_CEILING_ZERO",)),
    (candidate(recommendation=0, physical=0),
     0, ("PHYSICAL_CEILING_ZERO", "OZON_RECOMMENDATION_CEILING_ZERO")),
    (candidate(allowed=False, physical=100), 0, ("PHYSICALLY_INFEASIBLE",)),
    (candidate(complete=False), 10, ("ECONOMICS_INCOMPLETE",)),
])
def test_blockers_receive_zero_and_canonical_reasons(item, ceiling, reasons):
    decision = optimize_allocations([item], 100, thresholds()).decisions[0]
    assert decision.allocation_qty == 0
    assert decision.automatic_ceiling_qty == ceiling
    assert decision.eligible is False
    assert decision.reason_codes == reasons


def test_threshold_equality_and_low_route_confidence_pass():
    item = candidate(profit="10", margin="0.10", roi="0.20", route=RouteConfidence.LOW)
    result = optimize_allocations([item], 10, thresholds())
    assert allocations(result) == {"A": 10}
    assert result.decisions[0].eligible


@pytest.mark.parametrize("changes,reason", [
    ({"profit": "9"}, "BELOW_MIN_PROFIT_PER_UNIT"),
    ({"margin": "0.09"}, "BELOW_MIN_MARGIN_RATE"),
    ({"roi": "0.19"}, "BELOW_MIN_ROI"),
    ({"margin": None}, "MARGIN_RATE_UNAVAILABLE"),
    ({"roi": None}, "ROI_UNAVAILABLE"),
])
def test_each_metric_failure_blocks(changes, reason):
    decision = optimize_allocations([candidate(**changes)], 10, thresholds()).decisions[0]
    assert not decision.eligible and decision.allocation_qty == 0
    assert reason in decision.reason_codes


def test_multiple_failures_use_canonical_order():
    decision = optimize_allocations(
        [candidate(profit="-1", margin="-2", roi="-3")], 10, thresholds()
    ).decisions[0]
    assert decision.reason_codes == (
        "NON_POSITIVE_PROFIT", "BELOW_MIN_PROFIT_PER_UNIT",
        "BELOW_MIN_MARGIN_RATE", "BELOW_MIN_ROI",
    )


@pytest.mark.parametrize("profit", ["-1", "0"])
def test_non_positive_profit_is_never_allocated_even_with_negative_threshold(profit):
    result = optimize_allocations(
        [candidate(profit=profit)], 10, thresholds(profit="-100", margin="-100", roi="-100"))
    assert allocations(result) == {"A": 0}
    assert result.decisions[0].reason_codes == ("NON_POSITIVE_PROFIT",)
    assert result.unallocated_stock == 10


def distortion(cluster, confidence):
    return RecommendationDistortionSignal("SKU-1", cluster, confidence, (), ("fixture",))


@pytest.mark.parametrize("items,winner", [
    ([candidate("A", recommendation=1, route=RouteConfidence.LOW),
      candidate("B", recommendation=1, route=RouteConfidence.HIGH)], "B"),
    ([candidate("A", recommendation=1, distortion=distortion("A", SignalConfidence.HIGH)),
      candidate("B", recommendation=1, distortion=distortion("B", SignalConfidence.LOW))], "B"),
    ([candidate("A", recommendation=1), candidate("B", recommendation=2)], "B"),
    ([candidate("B", recommendation=1), candidate("A", recommendation=1)], "A"),
])
def test_canonical_tie_breaks(items, winner):
    result = optimize_allocations(items, 1, thresholds())
    assert allocations(result)[winner] == 1


def test_input_permutations_produce_identical_result():
    items = [candidate("C", recommendation=2, profit="20"),
             candidate("A", recommendation=2, profit="30"),
             candidate("B", recommendation=3, profit="20")]
    results = {optimize_allocations(order, 4, thresholds()) for order in permutations(items)}
    assert len(results) == 1
    result = results.pop()
    assert tuple(item.cluster_id for item in result.decisions) == ("A", "B", "C")
    assert allocations(result) == {"A": 2, "B": 2, "C": 0}
    assert result.decisions[2].reason_codes[-1] == "SELLER_STOCK_EXHAUSTED"


def test_global_binding_reasons_and_eligible_capacity():
    eligible = candidate(recommendation=5)
    blocked = candidate("B", recommendation=20, profit="0")
    assert optimize_allocations([eligible], 0, thresholds()).binding_reasons == (
        "ZERO_AVAILABLE_STOCK", "SELLER_STOCK_LIMIT")
    assert optimize_allocations([blocked], 0, thresholds()).binding_reasons == (
        "ZERO_AVAILABLE_STOCK", "NO_ELIGIBLE_CAPACITY")
    assert optimize_allocations([blocked], 3, thresholds()).binding_reasons == ("NO_ELIGIBLE_CAPACITY",)
    equal = optimize_allocations([eligible, blocked], 5, thresholds())
    assert equal.eligible_capacity_qty == 5
    assert equal.binding_reasons == ("SELLER_STOCK_EQUALS_CANDIDATE_CEILINGS",)


def test_high_precision_decimal_uses_local_context_without_quantization():
    original = getcontext().copy()
    profit = "1.123456789012345678901234567890123456789"
    result = optimize_allocations([candidate(profit=profit)], 3, thresholds(profit="0"))
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_EVEN
        expected = Decimal(profit) * 3
        quantized = Decimal(profit).quantize(Decimal("0.01"))
    assert result.objective_profit != quantized
    assert result.objective_profit == expected
    assert getcontext().prec == original.prec
    assert getcontext().rounding == original.rounding
    assert getcontext().flags == original.flags


@pytest.mark.parametrize("items,stock,error", [
    ([], 1, ValueError),
    ([candidate(), candidate("B", sku="SKU-2")], 1, ValueError),
    ([candidate(), candidate()], 1, ValueError),
    ([candidate()], -1, ValueError),
    ([candidate()], 1.5, TypeError),
    ([candidate()], True, TypeError),
])
def test_call_validation(items, stock, error):
    with pytest.raises(error):
        optimize_allocations(items, stock, thresholds())


@pytest.mark.parametrize("value", [1.0, Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_threshold_fields_must_be_finite_decimals(value):
    bad = OptimizerThresholds(value, Decimal("0"), Decimal("0"))
    with pytest.raises((TypeError, ValueError)):
        optimize_allocations([candidate()], 1, bad)
    with pytest.raises(TypeError):
        optimize_allocations([candidate()], 1, object())


def test_contracts_results_and_inputs_are_immutable():
    item = candidate()
    result = optimize_allocations([item], 1, thresholds())
    assert isinstance(result, OptimizationResult)
    assert isinstance(result.decisions[0], AllocationDecision)
    assert item == candidate()
    with pytest.raises(FrozenInstanceError):
        result.allocated_qty = 2
    with pytest.raises(FrozenInstanceError):
        result.decisions[0].allocation_qty = 2
