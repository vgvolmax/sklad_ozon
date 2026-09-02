from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from backend.decision import (
    HorizonComparability, ScenarioSettings, calculate_need, forecast_horizon,
)
from backend.supply.contracts import AllocationObjective


BASE = dict(
    sku="SKU-1", destination_cluster_id="Москва", weekly_rate=Decimal("10"),
    horizon_days=10, fbo_stock=3, inbound_qty=2, include_inbound=True,
    ozon_recommended_qty=8, ozon_horizon_days=10,
)


def need(**changes):
    return calculate_need(**(BASE | changes))


def test_need_rounds_only_after_stock_and_inbound_subtraction():
    result = need()
    assert result.raw_demand_forecast == Decimal("100") / Decimal("7")
    assert result.calculated_need_qty == 10


def test_forecast_is_decimal_and_has_no_buffer():
    assert forecast_horizon(Decimal("10"), 10) == Decimal("100") / Decimal("7")


def test_inbound_switch_changes_need_but_preserves_visible_quantity():
    included = need()
    excluded = need(include_inbound=False)
    assert included.calculated_need_qty == 10
    assert excluded.calculated_need_qty == 12
    assert excluded.inbound_qty == 2


def test_unknown_inbound_blocks_only_when_enabled():
    blocked = need(inbound_qty=None)
    calculated = need(inbound_qty=None, include_inbound=False)
    assert (blocked.calculated_need_qty, blocked.complete) == (None, False)
    assert blocked.blocker_codes == ("MISSING_INBOUND_QTY",)
    assert calculated.calculated_need_qty == 12
    assert calculated.complete is True


@pytest.mark.parametrize(("changes", "blocker"), [
    ({"fbo_stock": None}, "MISSING_FBO_STOCK"),
    ({"weekly_rate": None}, "MISSING_DEMAND_ESTIMATE"),
])
def test_missing_own_evidence_is_not_treated_as_zero(changes, blocker):
    result = need(**changes)
    assert result.calculated_need_qty is None
    assert result.complete is False
    assert blocker in result.blocker_codes
    if "weekly_rate" in changes:
        assert result.raw_demand_forecast is None


def test_negative_need_is_a_real_calculated_zero():
    result = need(fbo_stock=100)
    assert result.calculated_need_qty == 0
    assert result.complete is True


@pytest.mark.parametrize(("recommendation", "ozon_days", "own_days", "expected"), [
    (10, 56, 56, HorizonComparability.SAME_HORIZON),
    (100, 56, 28, HorizonComparability.DIFFERENT_HORIZON),
    (10, None, 10, HorizonComparability.OZON_HORIZON_UNKNOWN),
    (None, 10, 10, HorizonComparability.OZON_RECOMMENDATION_MISSING),
])
def test_horizon_comparability_preserves_original_ozon_values(
    recommendation, ozon_days, own_days, expected,
):
    result = need(ozon_recommended_qty=recommendation,
                  ozon_horizon_days=ozon_days, horizon_days=own_days)
    assert result.comparability is expected
    assert result.ozon_recommended_qty == recommendation
    assert result.ozon_horizon_days == ozon_days
    assert result.complete is True


def test_zero_ozon_allows_unit_delta_but_not_percentage_division():
    result = need(ozon_recommended_qty=0)
    assert result.delta_qty == result.calculated_need_qty
    assert result.delta_pct is None


def test_positive_ozon_delta_percentage_uses_decimal():
    result = need(ozon_recommended_qty=5)
    assert result.delta_qty == 5
    assert result.delta_pct == Decimal("1")


@pytest.mark.parametrize("recommendation", [None, 0, 10, 100, 1000])
def test_ozon_recommendation_never_changes_own_need(recommendation):
    assert need(ozon_recommended_qty=recommendation).calculated_need_qty == 10


@pytest.mark.parametrize("horizon", [0, -1])
def test_scenario_rejects_nonpositive_horizon(horizon):
    with pytest.raises(ValueError):
        ScenarioSettings(horizon, True, AllocationObjective.MAX_PROFIT)


@pytest.mark.parametrize(("args", "error"), [
    ((True, True, AllocationObjective.MAX_PROFIT), TypeError),
    ((7, 1, AllocationObjective.MAX_PROFIT), TypeError),
    ((7, True, "max_profit"), TypeError),
])
def test_scenario_requires_exact_contract_types(args, error):
    with pytest.raises(error):
        ScenarioSettings(*args)


def test_contracts_are_immutable_and_objectives_are_exactly_supported_set():
    settings = ScenarioSettings(7, False, AllocationObjective.MAX_MARGIN)
    with pytest.raises(FrozenInstanceError):
        settings.horizon_days = 8
    assert set(AllocationObjective) == {
        AllocationObjective.MAX_PROFIT, AllocationObjective.MAX_MARGIN,
    }
