from datetime import date
from decimal import Decimal, getcontext

import pytest

from backend.analytics import AnalyticsWindow, DemandCell, DemandResult
from backend.analytics.demand_estimate import DemandRegime, estimate_destination_demand
from backend.domain.signals import SignalConfidence


def demand(values, *, destination="Москва", weeks=None):
    weeks = weeks or tuple((2026, index + 1) for index in range(len(values)))
    cells = tuple(
        DemandCell("SKU-1", year, week, destination, qty, 1)
        for (year, week), qty in zip(weeks, values)
        if qty is not None
    )
    window = AnalyticsWindow(date(2026, 3, 1), 2026, 9, tuple(weeks), 0, 0, 0)
    return DemandResult(cells, window)


@pytest.mark.parametrize(("values", "regime", "raw", "applied"), [
    ([10] * 4 + [20, 20, 20, 24], DemandRegime.GROWTH, Decimal("2"), Decimal("2")),
    ([20] * 4 + [10, 10, 10, 8], DemandRegime.DECLINE, Decimal("-1"), Decimal("-1")),
])
def test_confirmed_trends_apply_exact_half_impulse(values, regime, raw, applied):
    result = estimate_destination_demand(demand(values))[0]
    assert (result.regime, result.regime_confirmed) == (regime, True)
    assert (result.raw_adjustment, result.applied_adjustment) == (raw, applied)


@pytest.mark.parametrize("second", [Decimal("11"), Decimal("9")])
def test_exact_ten_percent_boundaries_are_stable(second):
    result = estimate_destination_demand(demand([10] * 4 + [second] * 4))[0]
    assert result.regime is DemandRegime.STABLE


@pytest.mark.parametrize(("values", "cap"), [
    ([10] * 4 + [20, 20, 20, 100], Decimal("4")),
    ([20] * 4 + [10, 10, 10, 0], Decimal("-2")),
])
def test_adjustment_is_capped_at_twenty_percent(values, cap):
    result = estimate_destination_demand(demand(values))[0]
    assert result.applied_adjustment == cap
    assert "ADJUSTMENT_CAPPED" in result.explanation_codes


def test_latest_week_can_challenge_growth_without_replacing_baseline():
    result = estimate_destination_demand(demand([10] * 4 + [20] * 4))[0]
    assert result.regime is DemandRegime.GROWTH
    assert result.regime_confirmed is False
    assert result.current_weekly_rate == Decimal("20")
    assert result.applied_adjustment == 0


@pytest.mark.parametrize("latest", [Decimal("9"), Decimal("11")])
def test_stable_confirmation_band_is_inclusive(latest):
    result = estimate_destination_demand(demand([10] * 7 + [latest]))[0]
    assert result.regime is DemandRegime.STABLE
    assert result.regime_confirmed is True


@pytest.mark.parametrize(("values", "confidence", "code"), [
    ([1, 7, 3, 5, 9], SignalConfidence.MEDIUM, "SHORT_HISTORY_MEDIAN"),
    ([1, 9, 3], SignalConfidence.LOW, "VERY_SHORT_HISTORY"),
])
def test_short_history_uses_all_week_median(values, confidence, code):
    result = estimate_destination_demand(demand(values))[0]
    expected = Decimal("5") if len(values) == 5 else Decimal("3")
    assert result.current_weekly_rate == expected
    assert result.m1 is None
    assert result.confidence is confidence
    assert result.explanation_codes == (code,)


def test_very_short_history_uses_complete_low_confidence_fallback():
    result = estimate_destination_demand(demand([1, 9, 3]))[0]

    assert result.current_weekly_rate == Decimal("3")
    assert result.confidence is SignalConfidence.LOW
    assert result.regime is DemandRegime.INCOMPLETE
    assert result.applied_adjustment == Decimal("0")


@pytest.mark.parametrize("precision", [2, 10])
def test_demand_estimate_is_independent_of_global_decimal_context(precision):
    context = getcontext()
    original_precision = context.prec
    original_rounding = context.rounding

    try:
        context.prec = precision

        result = estimate_destination_demand(
            demand([100] * 4 + [123, 123, 123, 140])
        )[0]

        assert result.m1 == Decimal("100")
        assert result.m2 == Decimal("123")
        assert result.latest_week_qty == Decimal("140")
        assert result.regime is DemandRegime.GROWTH
        assert result.raw_adjustment == Decimal("8.5")
        assert result.applied_adjustment == Decimal("8.5")
        assert result.current_weekly_rate == Decimal("131.5")
        assert context.prec == precision
        assert context.rounding == original_rounding
    finally:
        context.prec = original_precision
        context.rounding = original_rounding


def test_zero_baseline_becomes_medium_confidence_transition():
    result = estimate_destination_demand(demand([0] * 4 + [4] * 4))[0]
    assert result.regime is DemandRegime.TRANSITION
    assert result.regime_confirmed is None
    assert result.current_weekly_rate == 4
    assert result.confidence is SignalConfidence.MEDIUM


def test_missing_cell_is_zero_filled_within_existing_destination_series():
    result = estimate_destination_demand(demand([10, 12, None, 11, 13]))[0]
    assert result.m2 == Decimal("11")
    assert result.current_weekly_rate == Decimal("11")


def test_only_latest_eight_weeks_affect_model_but_count_reports_eligible_weeks():
    result = estimate_destination_demand(demand([999, 999] + [10] * 4 + [20] * 4))[0]
    assert result.eligible_week_count == 10
    assert (result.m1, result.m2) == (Decimal("10"), Decimal("20"))


def test_route_substitution_cell_remains_destination_demand():
    result = estimate_destination_demand(demand([7], destination="Москва"))[0]
    assert result.destination_cluster_id == "Москва"
    assert result.current_weekly_rate == Decimal("7")


def test_no_demand_identity_returns_no_fabricated_zero():
    assert estimate_destination_demand(demand([])) == ()
