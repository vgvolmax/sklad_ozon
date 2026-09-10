from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from backend.domain.contracts import ProductEconomicsInput, SourceMode
from backend.supply import (
    AllocationDecision,
    AllocationObjective,
    OperationalSupplyFact,
    OptimizationResult,
    PlacementZoneKind,
    PlanFamily,
    RestrictionCapacityKind,
    RestrictionEligibility,
    ShippableLine,
    ShippablePlan,
    build_shippable_plan,
    round_up_to_pack,
)


def decision(cluster, qty, rank, *, sku="SKU-1"):
    return AllocationDecision(
        sku, cluster, qty, qty, Decimal("1"), Decimal(qty), True,
        ("ELIGIBLE_FOR_ALLOCATION",), rank,
    )


def result(*decisions, stock=100, sku="SKU-1"):
    allocated = sum(item.allocation_qty for item in decisions)
    return OptimizationResult(
        sku, stock, allocated, stock - allocated, allocated, Decimal(allocated),
        tuple(decisions), (), PlanFamily.CALCULATED, AllocationObjective.MAX_MARGIN,
    )


def product(*, sku="SKU-1", volume=Decimal("0.2"), available=9999):
    return ProductEconomicsInput(sku, "ART-1", None, available, None, None, volume)


def fact(cluster, *, sku="SKU-1", article="ART-1", pack=6,
         zone_kind=PlacementZoneKind.SINGLE, zones=("A",), reasons=()):
    return OperationalSupplyFact(
        sku, article, cluster, pack, zone_kind, zones,
        RestrictionEligibility.UNKNOWN, RestrictionCapacityKind.UNKNOWN, None,
        None, reasons,
    )


def build(*, decisions, stock=100, facts=None, products=None,
          source_mode=SourceMode.FILES, source_snapshot_id=None,
          analysis_snapshot_id="analysis-1", blocked_decision_rows=()):
    return build_shippable_plan(
        analysis_snapshot_id=analysis_snapshot_id,
        source_mode=source_mode,
        source_snapshot_id=source_snapshot_id,
        analysis_as_of=date(2026, 9, 10),
        horizon_days=56,
        include_inbound=True,
        objective=AllocationObjective.MAX_MARGIN,
        calculated_allocations=(result(*decisions, stock=stock),),
        products=(product(),) if products is None else products,
        supply_facts=tuple(fact(item.cluster_id) for item in decisions) if facts is None else facts,
        blocked_decision_rows=blocked_decision_rows,
    )


@pytest.mark.parametrize(("quantity", "pack", "expected"), [
    (0, 6, 0), (1, 6, 6), (5, 6, 6), (6, 6, 6),
    (17, 6, 18), (18, 6, 18), (19, 6, 24),
])
def test_round_up_to_pack_matrix(quantity, pack, expected):
    assert round_up_to_pack(quantity, pack) == expected


@pytest.mark.parametrize(("quantity", "pack", "error"), [
    (True, 6, TypeError), (1, False, TypeError), (1.0, 6, TypeError),
    (-1, 6, ValueError), (1, 0, ValueError),
])
def test_round_up_to_pack_strict_validation(quantity, pack, error):
    with pytest.raises(error):
        round_up_to_pack(quantity, pack)


def test_scarcity_uses_upstream_priority_not_cluster_name():
    plan = build(decisions=(decision("A", 3, 2), decision("Z", 17, 1)), stock=20)
    lines = {line.destination_cluster_id: line for line in plan.lines}
    assert (lines["Z"].rounded_target_qty, lines["Z"].shippable_qty) == (18, 18)
    assert (lines["A"].rounded_target_qty, lines["A"].shippable_qty) == (6, 0)
    assert "ROUNDED_UP_TO_WHOLE_PACK" in lines["Z"].reason_codes
    assert "WHOLE_PACK_LIMITED_BY_SELLER_STOCK" in lines["A"].reason_codes
    assert sum(line.shippable_qty or 0 for line in plan.lines) <= 20


@pytest.mark.parametrize(("qty", "stock", "expected"), [
    (17, 18, 18), (18, 18, 18), (0, 100, 0), (5, 5, 0), (5, 6, 6),
])
def test_zero_scarcity_and_exact_pack_matrix(qty, stock, expected):
    plan = build(decisions=(decision("A", qty, 1),), stock=stock)
    assert plan.lines[0].shippable_qty == expected
    assert expected == 0 or expected % 6 == 0


def test_exact_fit_and_filtering_are_all_cluster_and_never_reallocate():
    decisions = (decision("Moscow", 17, 1), decision("Perm", 12, 2),
                 decision("Kazan", 6, 3))
    plan = build(decisions=decisions, stock=36)
    assert {line.destination_cluster_id: line.shippable_qty for line in plan.lines} == {
        "Kazan": 6, "Moscow": 18, "Perm": 12,
    }
    selected = {line.destination_cluster_id: line.shippable_qty for line in plan.lines
                if line.destination_cluster_id in {"Moscow", "Perm"}}
    assert selected == {"Moscow": 18, "Perm": 12}


@pytest.mark.parametrize("reason", ["MISSING_PACK_MULTIPLICITY", "CONFLICTING_PACK_MULTIPLICITY"])
def test_missing_or_conflicting_pack_never_defaults_to_one(reason):
    plan = build(
        decisions=(decision("A", 17, 1),),
        facts=(fact("A", pack=None, reasons=(reason,)),),
    )
    line = plan.lines[0]
    assert line.rounded_target_qty is None
    assert line.rounding_delta_qty is None
    assert line.shippable_qty is None
    assert reason in line.reason_codes
    assert reason in {item.code for item in plan.diagnostics}


def test_unknown_pack_reserves_its_analytical_stock_before_lower_priority_line():
    decisions = (decision("Z", 17, 1), decision("A", 3, 2))
    facts = (fact("Z", pack=None, reasons=("MISSING_PACK_MULTIPLICITY",)), fact("A"))
    plan = build(decisions=decisions, facts=facts, stock=20)
    lines = {line.destination_cluster_id: line for line in plan.lines}
    assert lines["Z"].shippable_qty is None
    assert lines["A"].shippable_qty == 0


def test_volume_and_exact_multiple_placement_zones_are_preserved():
    plan = build(
        decisions=(decision("A", 17, 1),), stock=18,
        facts=(fact("A", zone_kind=PlacementZoneKind.MULTIPLE, zones=("A", "B")),),
    )
    line = plan.lines[0]
    assert line.unit_volume_l == Decimal("0.2")
    assert line.total_volume_l == Decimal("3.6")
    assert line.placement_zone_kind is PlacementZoneKind.MULTIPLE
    assert line.placement_zones == ("A", "B")


@pytest.mark.parametrize(("volume", "code"), [
    (None, "MISSING_UNIT_VOLUME"), (Decimal("0"), "INVALID_UNIT_VOLUME"),
    (Decimal("NaN"), "INVALID_UNIT_VOLUME"),
])
def test_missing_or_invalid_volume_is_unknown_not_zero(volume, code):
    plan = build(decisions=(decision("A", 17, 1),), stock=18,
                 products=(product(volume=volume),))
    line = plan.lines[0]
    assert line.shippable_qty == 18
    assert line.unit_volume_l is None and line.total_volume_l is None
    assert code in line.reason_codes


def test_unknown_zone_does_not_change_quantity_or_invent_zone():
    plan = build(
        decisions=(decision("A", 5, 1),), stock=6,
        facts=(fact("A", zone_kind=PlacementZoneKind.UNKNOWN, zones=(),
                    reasons=("UNKNOWN_PLACEMENT_ZONE",)),),
    )
    assert plan.lines[0].shippable_qty == 6
    assert plan.lines[0].placement_zones == ()
    assert "UNKNOWN_PLACEMENT_ZONE" in plan.lines[0].reason_codes


def test_plan_id_is_semantic_deterministic_and_input_order_independent():
    decisions = (decision("A", 3, 2), decision("Z", 17, 1))
    facts = (fact("A"), fact("Z"))
    first = build(decisions=decisions, facts=facts, stock=24)
    reordered = build(decisions=tuple(reversed(decisions)), facts=tuple(reversed(facts)), stock=24)
    assert first.shippable_plan_id == reordered.shippable_plan_id
    assert first.shippable_plan_id.startswith("sp_")
    changed_snapshot = build(decisions=decisions, facts=facts, stock=24,
                             analysis_snapshot_id="analysis-2")
    changed_pack = build(decisions=decisions,
                         facts=(fact("A", pack=12), fact("Z", pack=12)), stock=24)
    changed_zones = build(decisions=decisions,
                          facts=(fact("A", zones=("A", "B"), zone_kind=PlacementZoneKind.MULTIPLE), fact("Z")), stock=24)
    assert len({first.shippable_plan_id, changed_snapshot.shippable_plan_id,
                changed_pack.shippable_plan_id, changed_zones.shippable_plan_id}) == 4


def test_api_and_files_provenance_fail_closed():
    with pytest.raises(ValueError, match="source_snapshot_id"):
        build(decisions=(decision("A", 1, 1),), source_mode=SourceMode.API)
    with pytest.raises(ValueError, match="source_snapshot_id"):
        build(decisions=(decision("A", 1, 1),), source_snapshot_id="api-source")
    api = build(decisions=(decision("A", 1, 1),), source_mode=SourceMode.API,
                source_snapshot_id="api-source")
    assert api.source_snapshot_id == "api-source"
    other_source = build(decisions=(decision("A", 1, 1),), source_mode=SourceMode.API,
                         source_snapshot_id="other-source")
    assert other_source.shippable_plan_id != api.shippable_plan_id


def test_contracts_reject_bool_quantities_float_volume_and_are_immutable():
    kwargs = dict(
        sku="SKU", article="", destination_cluster_id="A", analytical_qty=1,
        rounded_target_qty=6, rounding_delta_qty=5, allocation_priority_rank=1,
        pack_multiple=6, resolved_seller_stock=6, shippable_qty=6,
        unit_volume_l=Decimal("0.2"), total_volume_l=Decimal("1.2"),
        placement_zone_kind=PlacementZoneKind.UNKNOWN, placement_zones=(), reason_codes=(),
    )
    line = ShippableLine(**kwargs)
    with pytest.raises(FrozenInstanceError):
        line.shippable_qty = 0
    for field in ("analytical_qty", "resolved_seller_stock", "shippable_qty"):
        with pytest.raises(TypeError):
            ShippableLine(**(kwargs | {field: True}))
    with pytest.raises(TypeError):
        ShippableLine(**(kwargs | {"unit_volume_l": 0.2}))
    with pytest.raises(ValueError):
        ShippableLine(**(kwargs | {"shippable_qty": 5, "total_volume_l": Decimal("1")}))
    with pytest.raises(ValueError, match="zero analytical"):
        ShippableLine(**(kwargs | {
            "analytical_qty": 0, "rounding_delta_qty": 6,
        }))
    with pytest.raises(ValueError, match="rounding_delta_qty"):
        ShippableLine(**(kwargs | {"rounding_delta_qty": 999}))
    with pytest.raises(ValueError, match="missing pack"):
        ShippableLine(**(kwargs | {
            "pack_multiple": None, "rounded_target_qty": 6,
        }))


def test_builder_rejects_scenario_objective_mismatch():
    allocation = result(decision("A", 1, 1), stock=6)
    with pytest.raises(ValueError, match="objective"):
        build_shippable_plan(
            analysis_snapshot_id="analysis", source_mode=SourceMode.FILES,
            source_snapshot_id=None, analysis_as_of=date(2026, 9, 10),
            horizon_days=56, include_inbound=True,
            objective=AllocationObjective.MAX_PROFIT,
            calculated_allocations=(allocation,), products=(product(),),
            supply_facts=(fact("A"),),
        )


def test_plan_rejects_duplicate_identity_and_priority():
    line = build(decisions=(decision("A", 1, 1),), stock=6).lines[0]
    common = dict(
        shippable_plan_id="sp_test", analysis_snapshot_id="analysis",
        source_mode=SourceMode.FILES, source_snapshot_id=None,
        analysis_as_of=date(2026, 9, 10), horizon_days=56, include_inbound=True,
        objective=AllocationObjective.MAX_MARGIN, diagnostics=(),
    )
    with pytest.raises(ValueError, match="duplicate"):
        ShippablePlan(**common, lines=(line, line))
