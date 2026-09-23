from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from backend.domain.contracts import RestrictionCapacityKind, SourceMode
from backend.project import WorkingQuantityOverride
from backend.supply import AllocationObjective, PlacementZoneKind, ShippableLine, ShippablePlan
from backend.working_plan import materialize_working_plan, validate_override_quantity


def line(cluster='Moscow', system=40, pack=40, stock=100, *, sku='SKU', kind=RestrictionCapacityKind.UNKNOWN, cap=None):
    analytical = system or 0
    return ShippableLine(sku, 'ART', cluster, analytical, system, 0, 1, pack, stock,
        system, Decimal('0.5'), Decimal('0.5') * system,
        PlacementZoneKind.SINGLE, ('A',), (), 'unknown', kind, cap)


def plan(*lines):
    return ShippablePlan('sp_1', 'as_1', SourceMode.FILES, None, date(2026, 9, 21),
        56, True, AllocationObjective.MAX_MARGIN, tuple(lines), ())


def override(qty, *, base=40, pack=40):
    return WorkingQuantityOverride(qty, 'sp_old', base, pack, '2026-09-21T11:30:00+03:00')


def test_default_follows_system_and_id_is_content_addressed():
    first = materialize_working_plan(plan(line()), {})
    second = materialize_working_plan(plan(line()), {})
    assert first == second
    assert first.working_plan_id.startswith('wp_')
    assert first.lines[0].working_qty == first.lines[0].system_qty == 40
    assert first.ready_count == 1


def test_override_is_separate_and_changed_recommendation_survives():
    current = materialize_working_plan(plan(line(system=80, stock=120)), {'SKU': {'Moscow': override(40)}})
    row = current.lines[0]
    assert (row.system_qty, row.working_qty, row.delta_qty) == (80, 40, -40)
    assert row.recommendation_changed and row.status == 'ATTENTION'
    assert 'RECOMMENDATION_CHANGED' in row.reason_codes


def test_persisted_override_counts_separately_when_it_matches_recommendation():
    current = materialize_working_plan(
        plan(line(system=80, stock=120)), {'SKU': {'Moscow': override(80)}})
    assert current.overridden_count == 1
    assert current.active_override_count == 0


def test_pack_change_blocks_old_override_without_rounding_it():
    result = materialize_working_plan(plan(line(system=100, pack=50, stock=200)),
                                      {'SKU': {'Moscow': override(80)}})
    assert result.lines[0].working_qty == 80
    assert result.lines[0].status == 'BLOCKED'
    assert 'OVERRIDE_NOT_PACK_MULTIPLE' in result.lines[0].reason_codes


def test_orphan_is_retained_as_diagnostic_counter():
    result = materialize_working_plan(plan(line()), {'OTHER': {'Kazan': override(40)}})
    assert result.orphan_override_count == 1
    assert result.diagnostics[0].code == 'ORPHAN_OVERRIDES'


def test_unknown_system_stays_unknown_but_explicit_zero_is_allowed():
    unknown = replace(line(system=40), analytical_qty=1, rounded_target_qty=None,
                      rounding_delta_qty=None, shippable_qty=None, total_volume_l=None,
                      pack_multiple=None)
    assert materialize_working_plan(plan(unknown), {}).lines[0].working_qty is None
    zero = materialize_working_plan(plan(unknown), {'SKU': {'Moscow': override(0)}})
    assert zero.lines[0].working_qty == 0
    assert zero.lines[0].status == 'ATTENTION'


def test_known_zero_without_pack_or_stock_is_ready_system_decision():
    known_zero = replace(
        line(system=0), allocation_priority_rank=None, pack_multiple=None,
        resolved_seller_stock=None, capacity_kind=RestrictionCapacityKind.UNKNOWN,
    )
    row = materialize_working_plan(plan(known_zero), {}).lines[0]
    assert (row.system_qty, row.working_qty, row.override_qty) == (0, 0, None)
    assert row.status == 'READY'
    assert 'WORKING_QTY_UNKNOWN' not in row.reason_codes
    assert 'MANUAL_WITHOUT_SYSTEM_RECOMMENDATION' not in row.reason_codes


def test_zero_and_positive_clusters_aggregate_to_fully_known_total():
    current = materialize_working_plan(plan(
        replace(line('Moscow', system=0), allocation_priority_rank=None),
        line('Kazan', system=40),
    ), {})
    assert sum(row.working_qty for row in current.lines) == 40
    assert all(row.working_qty is not None for row in current.lines)
    assert current.ready_count == 2


@pytest.mark.parametrize('quantity,valid', [(0, True), (40, True), (80, True), (65, False)])
def test_input_pack_validation(quantity, valid):
    if valid:
        assert validate_override_quantity(line(), quantity) == quantity
    else:
        with pytest.raises(ValueError): validate_override_quantity(line(), quantity)


def test_aggregate_stock_blocks_every_sku_line_and_can_recover():
    base = plan(*(replace(line(cluster, system=0), allocation_priority_rank=None) for cluster in ('A', 'B', 'C')))
    blocked = materialize_working_plan(base, {'SKU': {'A': override(40), 'B': override(40), 'C': override(40)}})
    assert blocked.blocked_count == 3
    assert all('SKU_SELLER_STOCK_EXCEEDED' in row.reason_codes for row in blocked.lines)
    ready = materialize_working_plan(base, {'SKU': {'C': override(0)}})
    assert ready.blocked_count == 0


def test_known_and_unknown_capacity_semantics():
    finite = materialize_working_plan(plan(line(kind=RestrictionCapacityKind.FINITE, cap=80, stock=200)), {'SKU': {'Moscow': override(120)}})
    assert finite.lines[0].status == 'BLOCKED'
    assert 'KNOWN_CAPACITY_EXCEEDED' in finite.lines[0].reason_codes
    unknown = materialize_working_plan(plan(line(stock=200)), {'SKU': {'Moscow': override(80)}})
    assert unknown.lines[0].status == 'ATTENTION'
    assert 'NEEDS_OZON_VALIDATION' in unknown.lines[0].reason_codes


def test_manual_whole_pack_is_allowed_without_system_recommendation():
    unknown = replace(line(system=40, pack=20), analytical_qty=None,
                      rounded_target_qty=None, rounding_delta_qty=None,
                      allocation_priority_rank=None, shippable_qty=None,
                      total_volume_l=None,
                      capacity_kind=RestrictionCapacityKind.UNLIMITED)
    result = materialize_working_plan(plan(unknown),
        {'SKU': {'Moscow': override(40, base=None, pack=20)}})
    row = result.lines[0]
    assert row.system_qty is None
    assert row.working_qty == 40
    assert row.status == 'ATTENTION'
    assert 'MANUAL_WITHOUT_SYSTEM_RECOMMENDATION' in row.reason_codes
    assert 'NEEDS_OZON_VALIDATION' in row.reason_codes


def test_unknown_system_explicit_zero_is_override_and_reset_restores_unknown():
    unknown = replace(line(system=40, pack=20), analytical_qty=None,
                      rounded_target_qty=None, rounding_delta_qty=None,
                      allocation_priority_rank=None, shippable_qty=None,
                      total_volume_l=None)
    explicit_zero = materialize_working_plan(plan(unknown),
        {'SKU': {'Moscow': override(0, base=None, pack=20)}}).lines[0]
    assert explicit_zero.override_qty == 0
    assert explicit_zero.working_qty == 0
    assert explicit_zero.is_overridden is True
    reset = materialize_working_plan(plan(unknown), {}).lines[0]
    assert reset.override_qty is None
    assert reset.working_qty is None
    assert reset.is_overridden is False


def test_unknown_seller_stock_is_attention_not_zero_or_blocked():
    unknown = replace(line(system=40, pack=20), analytical_qty=None,
                      rounded_target_qty=None, rounding_delta_qty=None,
                      allocation_priority_rank=None, resolved_seller_stock=None,
                      shippable_qty=None, total_volume_l=None)
    result = materialize_working_plan(plan(unknown),
        {'SKU': {'Moscow': override(40, base=None, pack=20)}})
    row = result.lines[0]
    assert row.resolved_seller_stock is None
    assert row.status == 'ATTENTION'
    assert 'SELLER_STOCK_UNCONFIRMED' in row.reason_codes
