from datetime import date

import pytest

from backend.analytics import (
    ObservationCoverage,
    coverage_includes_latest_completed_week,
    fully_covered_completed_iso_weeks,
)
from backend.analytics.demand import aggregate_demand
from backend.analytics.demand_estimate import DemandRegime, estimate_destination_demand
from tests.analytics.test_demand_calendar_axis import order_at


def test_coverage_rejects_reverse_interval():
    with pytest.raises(ValueError, match="period_end"):
        ObservationCoverage(date(2026, 9, 2), date(2026, 9, 1))


def test_partial_boundary_weeks_are_not_eligible_for_zero_fill():
    coverage = ObservationCoverage(date(2025, 12, 24), date(2026, 1, 15))

    assert fully_covered_completed_iso_weeks(
        coverage=coverage, as_of=date(2026, 1, 20)
    ) == ((2026, 1), (2026, 2))


def test_cross_year_axis_preserves_real_iso_week_53():
    coverage = ObservationCoverage(
        date.fromisocalendar(2020, 52, 1), date.fromisocalendar(2021, 1, 7)
    )

    assert fully_covered_completed_iso_weeks(
        coverage=coverage, as_of=date.fromisocalendar(2021, 2, 3)
    ) == ((2020, 52), (2020, 53), (2021, 1))


def test_zero_fill_is_allowed_inside_proven_coverage():
    coverage = ObservationCoverage(
        date.fromisocalendar(2026, 27, 1), date.fromisocalendar(2026, 38, 7)
    )
    orders = tuple(
        order_at(iso_year=2026, iso_week=week, quantity=100)
        for week in range(27, 35)
    )

    demand = aggregate_demand(
        orders, date.fromisocalendar(2026, 39, 1), coverage=coverage
    )

    assert demand.window.included_weeks[-4:] == (
        (2026, 35), (2026, 36), (2026, 37), (2026, 38)
    )


def test_stale_coverage_keeps_history_but_marks_estimate_incomplete():
    coverage = ObservationCoverage(
        date.fromisocalendar(2026, 27, 1), date.fromisocalendar(2026, 34, 7)
    )
    orders = tuple(
        order_at(iso_year=2026, iso_week=week, quantity=100)
        for week in range(27, 35)
    )

    demand = aggregate_demand(
        orders, date.fromisocalendar(2026, 39, 1), coverage=coverage
    )
    estimate = estimate_destination_demand(demand)[0]

    assert demand.window.coverage_current is False
    assert estimate.current_weekly_rate == 100
    assert estimate.regime is DemandRegime.INCOMPLETE
    assert estimate.confidence.value == "low"
    assert "DEMAND_COVERAGE_NOT_CURRENT" in estimate.explanation_codes


def test_coverage_is_current_only_when_it_contains_latest_completed_week():
    as_of = date.fromisocalendar(2026, 35, 3)
    current = ObservationCoverage(
        date.fromisocalendar(2026, 27, 1), date.fromisocalendar(2026, 34, 7)
    )
    stale = ObservationCoverage(
        date.fromisocalendar(2026, 27, 1), date.fromisocalendar(2026, 33, 7)
    )

    assert coverage_includes_latest_completed_week(current, as_of=as_of)
    assert not coverage_includes_latest_completed_week(stale, as_of=as_of)
