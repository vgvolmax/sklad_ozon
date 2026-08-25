"""PR7 Task 15 supply feasibility and placement assessment behavior."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from backend.domain.signals import RecommendationDistortionSignal, SignalConfidence
from backend.economics import CalculationBases, RoundingMetadata, UnitEconomicsResult
from backend.ingestion.restrictions import RestrictionRecord, RestrictionState
from backend.supply import (
    PlacementInput,
    PlacementSource,
    RouteConfidence,
    WarehouseCapability,
    assess_feasibility,
    compare_placements,
)


def restriction(sku, warehouse, state):
    return RestrictionRecord(sku, warehouse, state, "fixture", state.value)


def economics(sku="SKU-1", cluster="Moscow", *, complete=True, profit="10"):
    value = Decimal(profit) if complete else None
    return UnitEconomicsResult(
        sku, cluster, Decimal("100"), Decimal("10"), Decimal("1"), Decimal("5"), Decimal("0"),
        Decimal("5"), Decimal("1"), Decimal("17"), Decimal("83"), Decimal("0"), Decimal("100"),
        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("73"), value,
        value / Decimal("100") if value is not None else None,
        value / Decimal("73") if value is not None else None, complete,
        () if complete else ("INCOMPLETE_LOGISTICS_COVERAGE",), CalculationBases(), (), RoundingMetadata(),
    )


def candidate(cluster="Moscow", *, sku="SKU-1", quantity=0,
              sources=(PlacementSource.COUNTERFACTUAL,), result=None, distortion=None):
    return PlacementInput(sku, cluster, quantity, sources, result or economics(sku, cluster),
                          distortion, RouteConfidence.MEDIUM)


def test_one_allowed_one_prohibited_is_feasible_and_reason_coded():
    result = assess_feasibility(
        "SKU-1", "Moscow",
        [restriction("SKU-1", "Moscow-A", RestrictionState.PROHIBITED),
         restriction("SKU-1", "Moscow-B", RestrictionState.ALLOWED)],
        [WarehouseCapability("Moscow-A", "Moscow"), WarehouseCapability("Moscow-B", "Moscow")],
    )
    assert result.allowed is True
    assert result.eligible_warehouses == ("Moscow-B",)
    assert result.reasons == ("PROHIBITED_WAREHOUSE_PRESENT", "ELIGIBLE_WAREHOUSE_FOUND")


def test_all_prohibited_unknown_missing_and_no_warehouse_fail_closed():
    warehouses = [WarehouseCapability("A", "Moscow"), WarehouseCapability("B", "Moscow")]
    prohibited = assess_feasibility("SKU-1", "Moscow", [
        restriction("SKU-1", "A", RestrictionState.PROHIBITED),
        restriction("SKU-1", "B", RestrictionState.PROHIBITED)], warehouses)
    assert (prohibited.allowed, prohibited.max_supply_qty, prohibited.eligible_warehouses) == (False, 0, ())
    assert prohibited.reasons == ("PROHIBITED_WAREHOUSE_PRESENT", "NO_EXPLICIT_ALLOWED_WAREHOUSE")

    unknown = assess_feasibility("SKU-1", "Moscow", [
        restriction("SKU-1", "A", RestrictionState.UNKNOWN)], warehouses[:1])
    assert unknown.reasons == ("UNKNOWN_RESTRICTION_STATE", "NO_EXPLICIT_ALLOWED_WAREHOUSE")
    missing = assess_feasibility("SKU-1", "Moscow", [], warehouses[:1])
    assert missing.reasons == ("RESTRICTION_DATA_MISSING", "NO_EXPLICIT_ALLOWED_WAREHOUSE")
    none = assess_feasibility("SKU-1", "Moscow", [], [WarehouseCapability("A", "Kazan")])
    assert (none.allowed, none.max_supply_qty, none.reasons) == (False, 0, ("NO_WAREHOUSES_FOR_CLUSTER",))


def test_sku_cluster_duplicate_and_conflict_isolation():
    warehouses = [WarehouseCapability("M", "Moscow"), WarehouseCapability("K", "Kazan")]
    rows = [
        restriction("SKU-2", "M", RestrictionState.PROHIBITED),
        restriction("SKU-1", "K", RestrictionState.PROHIBITED),
        restriction("SKU-1", "M", RestrictionState.ALLOWED),
        restriction("SKU-1", "M", RestrictionState.ALLOWED),
    ]
    result = assess_feasibility("SKU-1", "Moscow", rows, warehouses)
    assert result.eligible_warehouses == ("M",)
    assert result.reasons == ("ELIGIBLE_WAREHOUSE_FOUND",)
    conflict = assess_feasibility("SKU-1", "Moscow", rows + [
        restriction("SKU-1", "M", RestrictionState.UNKNOWN)], warehouses)
    assert conflict.eligible_warehouses == ()
    assert conflict.reasons == ("CONFLICTING_RESTRICTIONS", "NO_EXPLICIT_ALLOWED_WAREHOUSE")


@pytest.mark.parametrize("maxima,expected,reasons", [
    ((40,), 40, ("ELIGIBLE_WAREHOUSE_FOUND",)),
    ((50, 80), 50, ("CONSERVATIVE_WAREHOUSE_MAXIMUM", "ELIGIBLE_WAREHOUSE_FOUND")),
    ((None, 50), 50, ("CONSERVATIVE_WAREHOUSE_MAXIMUM", "ELIGIBLE_WAREHOUSE_FOUND")),
    ((None, None), None, ("ELIGIBLE_WAREHOUSE_FOUND",)),
    ((0,), 0, ("ZERO_PHYSICAL_CEILING", "ELIGIBLE_WAREHOUSE_FOUND")),
])
def test_warehouse_maximum_is_conservative_and_never_summed(maxima, expected, reasons):
    warehouses = [WarehouseCapability(chr(65 + index), "Moscow", maximum)
                  for index, maximum in enumerate(maxima)]
    rows = [restriction("SKU-1", warehouse.warehouse, RestrictionState.ALLOWED)
            for warehouse in warehouses]
    result = assess_feasibility("SKU-1", "Moscow", rows, warehouses)
    assert result.allowed is True
    assert result.max_supply_qty == expected
    assert result.reasons == reasons


def test_counterfactual_zero_recommendation_preserves_feasibility_and_economics():
    original = economics()
    assessment = compare_placements(
        [candidate(result=original)], [restriction("SKU-1", "M", RestrictionState.ALLOWED)],
        [WarehouseCapability("M", "Moscow")],
    )[0]
    assert assessment.feasibility.allowed is True
    assert assessment.ozon_recommended_qty == 0
    assert assessment.economics is original
    assert assessment.status_codes == ("COUNTERFACTUAL_CANDIDATE", "AUTOMATIC_CEILING_ZERO")
    assert not hasattr(assessment, "allocation") and not hasattr(assessment, "allocated_qty")


def test_sources_statuses_and_output_sorting_are_deterministic():
    candidates = [
        candidate("Kazan", sku="SKU-2", quantity=100, sources=(PlacementSource.RECOMMENDED,)),
        candidate("Moscow", sources=(PlacementSource.RECOMMENDED, PlacementSource.OBSERVED)),
        candidate("Kazan", quantity=10, sources=(PlacementSource.COUNTERFACTUAL, PlacementSource.OBSERVED)),
    ]
    warehouses = [WarehouseCapability("M", "Moscow"), WarehouseCapability("K", "Kazan")]
    rows = [restriction(sku, warehouse, RestrictionState.ALLOWED)
            for sku in ("SKU-1", "SKU-2") for warehouse in ("M", "K")]
    results = compare_placements(candidates, rows, warehouses)
    assert [(item.sku, item.cluster_id) for item in results] == [
        ("SKU-1", "Kazan"), ("SKU-1", "Moscow"), ("SKU-2", "Kazan")]
    assert results[1].status_codes[:2] == ("OBSERVED_CANDIDATE", "RECOMMENDED_CANDIDATE")
    assert results[2].status_codes == ("RECOMMENDED_CANDIDATE",)


def test_economics_completeness_profit_and_physical_feasibility_remain_separate():
    allowed = [restriction("SKU-1", "M", RestrictionState.ALLOWED)]
    warehouse = [WarehouseCapability("M", "Moscow")]
    incomplete = economics(complete=False)
    assessed = compare_placements([candidate(result=incomplete)], allowed, warehouse)[0]
    assert assessed.feasibility.allowed and assessed.economics is incomplete
    assert "ECONOMICS_INCOMPLETE" in assessed.status_codes

    negative = economics(profit="-10")
    assessed = compare_placements([candidate(result=negative)], allowed, warehouse)[0]
    assert assessed.feasibility.allowed and assessed.economics.profit_per_unit < 0
    assert "PHYSICALLY_INFEASIBLE" not in assessed.status_codes

    profitable = economics(profit="10")
    assessed = compare_placements([candidate(result=profitable)], [
        restriction("SKU-1", "M", RestrictionState.PROHIBITED)], warehouse)[0]
    assert not assessed.feasibility.allowed and assessed.economics is profitable
    assert assessed.status_codes[1:3] == ("PHYSICALLY_INFEASIBLE", "PHYSICAL_CEILING_ZERO")


def test_distortion_is_explainability_only_and_identity_is_validated():
    signal = RecommendationDistortionSignal("SKU-1", "Moscow", SignalConfidence.HIGH, (), ("fixture",))
    assessed = compare_placements([candidate(quantity=7, distortion=signal)], [
        restriction("SKU-1", "M", RestrictionState.ALLOWED)], [WarehouseCapability("M", "Moscow")])[0]
    assert assessed.distortion_signal is signal and assessed.ozon_recommended_qty == 7
    assert assessed.status_codes[-1] == "RECOMMENDATION_DISTORTION_SIGNAL"
    with pytest.raises(ValueError, match="distortion"):
        candidate(distortion=replace(signal, recommended_cluster_id="Kazan"))


def test_candidate_identity_duplicates_and_validation():
    with pytest.raises(ValueError, match="economics"):
        candidate(result=economics(sku="SKU-2"))
    with pytest.raises(ValueError, match="economics"):
        candidate(result=economics(cluster="Kazan"))
    item = candidate()
    with pytest.raises(ValueError, match="Duplicate candidate"):
        compare_placements([item, item], [], [])


@pytest.mark.parametrize("changes", [
    {"sku": " "}, {"cluster_id": ""}, {"ozon_recommended_qty": -1},
    {"ozon_recommended_qty": 1.5}, {"ozon_recommended_qty": True}, {"sources": ()},
    {"sources": (PlacementSource.OBSERVED, PlacementSource.OBSERVED)},
])
def test_malformed_placement_input_is_rejected(changes):
    values = dict(sku="SKU-1", cluster_id="Moscow", ozon_recommended_qty=0,
                  sources=(PlacementSource.COUNTERFACTUAL,), economics=economics(),
                  distortion_signal=None, route_confidence=RouteConfidence.LOW)
    values.update(changes)
    with pytest.raises((TypeError, ValueError)):
        PlacementInput(**values)


@pytest.mark.parametrize("args", [
    ("", "Moscow", None), ("A", " ", None), ("A", "Moscow", -1),
    ("A", "Moscow", 1.5), ("A", "Moscow", True),
])
def test_malformed_warehouse_capability_is_rejected(args):
    with pytest.raises((TypeError, ValueError)):
        WarehouseCapability(*args)


def test_contracts_and_inputs_are_immutable():
    capability = WarehouseCapability("M", "Moscow", 5)
    item = candidate()
    originals = capability, item, item.economics
    compare_placements([item], [restriction("SKU-1", "M", RestrictionState.ALLOWED)], [capability])
    assert (capability, item, item.economics) == originals
    with pytest.raises(FrozenInstanceError):
        capability.cluster_id = "Kazan"
