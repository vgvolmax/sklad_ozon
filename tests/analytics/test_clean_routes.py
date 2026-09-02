"""Auditable observed and stockout-cleaned historical route distributions."""

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal

import pytest

from backend.analytics.clean_routes import (
    CleanRouteFallbackStatus,
    build_clean_route_profile,
)
from backend.analytics.routes import RouteProfile, build_route_profile
from backend.domain.contracts import OrderLifecycle, OrderRecord
from backend.domain.signals import (
    AvailabilityCorroboration,
    SignalConfidence,
    StockoutSignal,
)


def _order(sku, day, origin, destination, quantity):
    return OrderRecord(
        sku=sku,
        accepted_at=day,
        origin_cluster=origin,
        destination_cluster=destination,
        quantity=quantity,
        lifecycle=OrderLifecycle.FULFILLED,
    )


def _profile(*rows):
    return build_route_profile(
        (_order(*row) for row in rows), as_of=date(2026, 8, 31)
    )


def _canonical():
    return _profile(
        ("SKU-1", "2026-08-10", "Москва", "Москва", 90),
        ("SKU-1", "2026-08-10", "Казань", "Москва", 5),
        ("SKU-1", "2026-08-10", "Казань", "Казань", 100),
        ("SKU-1", "2026-08-17", "Москва", "Москва", 20),
        ("SKU-1", "2026-08-17", "Казань", "Москва", 60),
        ("SKU-1", "2026-08-17", "Казань", "Москва", 5),
        ("SKU-1", "2026-08-17", "Казань", "Казань", 120),
    )


def _signal(
    confidence=SignalConfidence.HIGH,
    *,
    eligible=True,
    sku="SKU-1",
    destination="Москва",
    week="2026-W34",
):
    return StockoutSignal(
        sku=sku,
        destination_cluster_id=destination,
        historical_evidence_strength=SignalConfidence.HIGH,
        route_cleaning_eligible=eligible,
        confidence=confidence,
        baseline_week="2026-W33",
        observed_week=week,
        baseline_local_share=Decimal("0.9"),
        observed_local_share=Decimal("0.2"),
        demand_retention=Decimal("0.95"),
        availability_corroboration=AvailabilityCorroboration.SUPPORTS,
        replacement_origins=(),
        explanation_codes=("TEST",),
    )


def _cell(cells, origin, destination):
    return next(
        cell for cell in cells
        if cell.sku == "SKU-1"
        and cell.origin_cluster_id == origin
        and cell.destination_cluster_id == destination
    )


def test_canonical_destination_week_is_excluded_from_every_origin_and_recomputed():
    observed = _canonical()
    before = replace(observed, routes=tuple(observed.routes))

    result = build_clean_route_profile(observed, [_signal()])

    assert observed == before
    observed_moscow = _cell(result.observed_routes, "Казань", "Москва")
    observed_kazan = _cell(result.observed_routes, "Казань", "Казань")
    assert (observed_moscow.quantity, observed_kazan.quantity) == (70, 220)
    assert observed_moscow.share == Decimal(70) / Decimal(290)
    assert observed_kazan.share == Decimal(220) / Decimal(290)

    clean_moscow = _cell(result.clean_routes, "Казань", "Москва")
    clean_kazan = _cell(result.clean_routes, "Казань", "Казань")
    assert (clean_moscow.quantity, clean_kazan.quantity) == (5, 220)
    assert clean_moscow.share == Decimal(5) / Decimal(225)
    assert clean_kazan.share == Decimal(220) / Decimal(225)

    evidence = {(row.origin_cluster_id, row.destination_cluster_id, row.quantity)
                for row in result.excluded_routes}
    assert evidence == {("Москва", "Москва", 20), ("Казань", "Москва", 65)}
    assert all(row.iso_week == 34 and row.stockout_observed_week == "2026-W34"
               for row in result.excluded_routes)
    kazan_summary = next(row for row in result.summaries
                         if row.origin_cluster_id == "Казань")
    assert (kazan_summary.observed_observation_count,
            kazan_summary.excluded_observation_count) == (5, 2)


def test_every_donor_into_contaminated_destination_week_is_excluded():
    observed = _profile(
        ("SKU-1", "2026-08-17", "Москва", "Москва", 20),
        ("SKU-1", "2026-08-17", "Казань", "Москва", 65),
        ("SKU-1", "2026-08-17", "Санкт-Петербург", "Москва", 10),
        ("SKU-1", "2026-08-17", "Казань", "Казань", 120),
    )
    result = build_clean_route_profile(observed, [_signal()])
    assert {row.origin_cluster_id for row in result.excluded_routes} == {
        "Москва", "Казань", "Санкт-Петербург"
    }
    assert [(row.origin_cluster_id, row.destination_cluster_id)
            for row in result.clean_routes] == [("Казань", "Казань")]


def test_explicit_eligibility_controls_exclusion_independently_of_confidence():
    observed = _canonical()
    eligible_low = build_clean_route_profile(
        observed, [_signal(SignalConfidence.LOW, eligible=True)]
    )
    assert len(eligible_low.excluded_routes) == 2
    assert all(row.stockout_confidence is SignalConfidence.LOW
               for row in eligible_low.excluded_routes)

    ineligible_high = build_clean_route_profile(
        observed, [_signal(SignalConfidence.HIGH, eligible=False)]
    )
    assert ineligible_high.excluded_routes == ()
    assert ineligible_high.clean_routes == ineligible_high.observed_routes


def test_no_clean_history_reports_observed_fallback_without_fake_cell():
    observed = _profile(("SKU-X", "2026-08-17", "Казань", "Москва", 50))
    result = build_clean_route_profile(observed, [_signal(sku="SKU-X")])
    assert len(result.observed_routes) == 1
    assert result.observed_routes[0].share == Decimal(1)
    assert result.clean_routes == ()
    summary = result.summaries[0]
    assert (summary.observed_total_quantity, summary.clean_total_quantity) == (50, 0)
    assert summary.clean_share_sum is None
    assert summary.fallback_status is CleanRouteFallbackStatus.OBSERVED_FALLBACK


def test_signal_identity_is_sku_destination_and_week_and_supports_multiple_destinations():
    observed = _profile(
        ("SKU-1", "2026-08-10", "Казань", "Москва", 5),
        ("SKU-1", "2026-08-17", "Казань", "Москва", 65),
        ("SKU-1", "2026-08-17", "Казань", "Казань", 120),
        ("SKU-1", "2026-08-17", "Казань", "Тверь", 30),
        ("SKU-2", "2026-08-17", "Казань", "Москва", 40),
    )
    result = build_clean_route_profile(
        observed, [_signal(), _signal(destination="Тверь")]
    )
    excluded = {(row.sku, row.iso_week, row.destination_cluster_id, row.quantity)
                for row in result.excluded_routes}
    assert excluded == {
        ("SKU-1", 34, "Москва", 65),
        ("SKU-1", 34, "Тверь", 30),
    }
    clean = {(row.sku, row.destination_cluster_id): row.quantity
             for row in result.clean_routes}
    assert clean[("SKU-1", "Москва")] == 5
    assert clean[("SKU-1", "Казань")] == 120
    assert clean[("SKU-2", "Москва")] == 40


def test_duplicate_signal_uses_highest_confidence_and_excludes_once():
    observed = _canonical()
    result = build_clean_route_profile(
        observed,
        [_signal(SignalConfidence.MEDIUM), _signal(SignalConfidence.HIGH), _signal()],
    )
    assert len(result.excluded_routes) == 2
    assert all(row.stockout_confidence is SignalConfidence.HIGH
               for row in result.excluded_routes)


@pytest.mark.parametrize("week", ["2026-WXX", "2026-W99", "2026-W1", "2026-34"])
def test_malformed_stockout_week_is_rejected(week):
    with pytest.raises(ValueError, match="observed_week"):
        build_clean_route_profile(_canonical(), [_signal(week=week)])


def test_inconsistent_route_profile_week_is_rejected():
    observed = _canonical()
    invalid = RouteProfile(
        routes=(replace(observed.routes[0], iso_week=32),), window=observed.window
    )
    with pytest.raises(ValueError, match="included_weeks"):
        build_clean_route_profile(invalid, ())


def test_empty_inputs_and_contracts_are_immutable():
    observed = _canonical()
    result = build_clean_route_profile(observed, ())
    assert result.clean_routes == result.observed_routes
    assert result.excluded_routes == ()
    assert all(summary.fallback_status is CleanRouteFallbackStatus.CLEAN_AVAILABLE
               for summary in result.summaries)
    with pytest.raises(FrozenInstanceError):
        result.summaries[0].sku = "changed"

    empty = _profile()
    assert build_clean_route_profile(empty, ()).observed_routes == ()
    assert build_clean_route_profile(empty, ()).clean_routes == ()
    assert build_clean_route_profile(empty, ()).summaries == ()
