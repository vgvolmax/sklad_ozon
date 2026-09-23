from dataclasses import replace
from decimal import Decimal

import pytest

from backend.domain.contracts import RestrictionCapacityKind
from backend.project import WorkingQuantityOverride
from backend.shipment.candidates import build_candidate_result
from backend.shipment.contracts import ShipmentMethod
from backend.shipment.working_input import build_shipment_input, WorkingPlanIdentityError
from backend.working_plan import materialize_working_plan
from backend.ozon.handoff import HandoffPointStore
from tests.shipment.conftest import make_line, make_plan
from tests.shipment.test_candidates import scenario


def override(quantity, line, plan):
    return {line.sku: {line.destination_cluster_id: WorkingQuantityOverride(
        quantity, plan.shippable_plan_id, line.shippable_qty, line.pack_multiple,
        "2026-09-21T00:00:00+03:00")}}


def test_manual_quantity_and_volume_are_execution_authority():
    line = make_line("123", "Moscow", 40, volume="0.5", pack=1)
    plan = make_plan((line,))
    working = materialize_working_plan(plan, override(80, line, plan))
    execution = build_shipment_input(plan, working)
    result = build_candidate_result(
        shipment_input=execution, scenario=scenario(("Moscow",), (ShipmentMethod.DIRECT,)),
        seller_warehouses=(), handoff_store=HandoffPointStore())
    assignment = result.candidates[0].assignments[0]
    assert assignment.quantity == 80
    assert assignment.total_volume_l == Decimal("40.0")


def test_manual_quantity_without_system_recommendation_reaches_candidate_exactly():
    line = replace(make_line("123", "Moscow", 20, volume="1.5", pack=20),
                   analytical_qty=None, rounded_target_qty=None, rounding_delta_qty=None,
                   allocation_priority_rank=None, shippable_qty=None, total_volume_l=None,
                   capacity_kind=RestrictionCapacityKind.UNKNOWN)
    plan = make_plan((line,))
    working = materialize_working_plan(plan, override(40, line, plan))
    execution = build_shipment_input(plan, working)
    assert execution.lines[0].quantity == 40
    result = build_candidate_result(
        shipment_input=execution, scenario=scenario(("Moscow",), (ShipmentMethod.DIRECT,)),
        seller_warehouses=(), handoff_store=HandoffPointStore())
    assignment = result.candidates[0].assignments[0]
    assert assignment.quantity == 40
    assert result.candidates[0].total_volume_l == Decimal("60.0")


def test_manual_zero_is_omitted():
    line = make_line("123", "Moscow", 40)
    plan = make_plan((line,))
    execution = build_shipment_input(plan, materialize_working_plan(plan, override(0, line, plan)))
    result = build_candidate_result(
        shipment_input=execution, scenario=scenario(("Moscow",)),
        seller_warehouses=(), handoff_store=HandoffPointStore())
    assert result.candidates == ()
    assert result.diagnostics[0].code == "EMPTY_SHIPMENT_SCOPE"


def test_selected_unresolved_blocked_row_is_outside_positive_scope():
    ready = make_line("ready", "Moscow", 40)
    blocked = replace(make_line("blocked", "Moscow", 40), pack_multiple=None,
                      rounded_target_qty=None, rounding_delta_qty=None,
                      shippable_qty=None, total_volume_l=None)
    plan = make_plan((ready, blocked))
    execution = build_shipment_input(plan, materialize_working_plan(plan, {}))
    result = build_candidate_result(
        shipment_input=execution, scenario=scenario(("Moscow",)),
        seller_warehouses=(), handoff_store=HandoffPointStore())
    assert len(result.candidates) == 1
    assert [(item.sku, item.quantity)
            for item in result.candidates[0].assignments] == [("ready", 40)]


def test_identity_coverage_is_exact():
    plan = make_plan((make_line("a", "Moscow", 1),))
    working = materialize_working_plan(plan, {})
    with pytest.raises(WorkingPlanIdentityError):
        build_shipment_input(plan, replace(working, lines=()))


def test_candidate_identity_changes_when_other_cluster_working_plan_changes():
    moscow = make_line("a", "Moscow", 40)
    kazan = make_line("b", "Kazan", 40)
    plan = make_plan((moscow, kazan))
    first = materialize_working_plan(plan, {})
    second = materialize_working_plan(plan, override(0, kazan, plan))
    kwargs = dict(scenario=scenario(("Moscow",)), seller_warehouses=(),
                  handoff_store=HandoffPointStore())
    first_candidate = build_candidate_result(
        shipment_input=build_shipment_input(plan, first), **kwargs).candidates[0]
    second_candidate = build_candidate_result(
        shipment_input=build_shipment_input(plan, second), **kwargs).candidates[0]
    assert first_candidate.assignments == second_candidate.assignments
    assert first_candidate.candidate_id != second_candidate.candidate_id
