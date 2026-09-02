"""PR5 Task 11 stockout and donor-distortion behavior."""

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal

import pytest

from backend.analytics.distortion import detect_recommendation_distortion
from backend.analytics.routes import build_route_profile
from backend.analytics.stockout import StockoutThresholds, detect_stockouts
from backend.domain.contracts import OrderLifecycle, OrderRecord
from backend.domain.signals import (
    AvailabilityCorroboration, SignalConfidence, StockoutSignal,
)
from backend.ingestion.availability import AvailabilityRecord


def _order(sku, day, origin, destination, quantity):
    return OrderRecord(sku=sku, quantity=quantity, origin_cluster=origin,
                       destination_cluster=destination,
                       lifecycle=OrderLifecycle.FULFILLED, accepted_at=day)


def _profile(*rows):
    return build_route_profile((_order(*row) for row in rows), as_of=date(2026, 8, 31))


def _canonical(extra=()):
    return _profile(
        ("SKU-1", "2026-08-10", "Москва", "Москва", 90),
        ("SKU-1", "2026-08-10", "Казань", "Москва", 5),
        ("SKU-1", "2026-08-10", "Санкт-Петербург", "Москва", 5),
        ("SKU-1", "2026-08-17", "Москва", "Москва", 19),
        ("SKU-1", "2026-08-17", "Казань", "Москва", 62),
        ("SKU-1", "2026-08-17", "Санкт-Петербург", "Москва", 14),
        *extra,
    )


def test_canonical_moscow_stockout_and_kazan_distortion_are_directional_and_exact():
    routes = _canonical()
    before = routes
    signals = detect_stockouts(routes)
    assert routes == before
    assert len(signals) == 1
    signal = signals[0]
    assert (signal.sku, signal.destination_cluster_id) == ("SKU-1", "Москва")
    assert all(item.destination_cluster_id != "Казань" for item in signals)
    assert (signal.baseline_week, signal.observed_week) == ("2026-W33", "2026-W34")
    assert signal.baseline_local_share == Decimal("0.9")
    assert signal.observed_local_share == Decimal(19) / Decimal(95)
    assert signal.baseline_local_share - signal.observed_local_share == Decimal("0.7")
    assert signal.demand_retention == Decimal("0.95")
    kazan = signal.replacement_origins[0]
    assert kazan.origin_cluster_id == "Казань"
    assert kazan.share_after - kazan.share_before == Decimal(62) / Decimal(95) - Decimal("0.05")
    distortions = detect_recommendation_distortion(signals, routes)
    assert routes == before and signals == (signal,)
    assert len(distortions) == 1
    distortion = distortions[0]
    assert distortion.recommended_cluster_id == "Казань"
    assert distortion.affected_destinations[0].destination_cluster_id == "Москва"
    assert not hasattr(distortion, "allocation") and not hasattr(distortion, "recommended_quantity")


def test_threshold_boundaries_are_inclusive_including_retention():
    shares = _profile(
        ("S", "2026-08-10", "D", "D", 60), ("S", "2026-08-10", "A", "D", 20),
        ("S", "2026-08-10", "B", "D", 20), ("S", "2026-08-17", "D", "D", 30),
        ("S", "2026-08-17", "A", "D", 40), ("S", "2026-08-17", "B", "D", 30),
    )
    assert len(detect_stockouts(shares)) == 1
    retention = _profile(
        ("S", "2026-08-10", "D", "D", 60), ("S", "2026-08-10", "A", "D", 40),
        ("S", "2026-08-17", "D", "D", 18), ("S", "2026-08-17", "A", "D", 42),
    )
    assert detect_stockouts(retention)[0].demand_retention == Decimal("0.6")


@pytest.mark.parametrize("rows", [
    # low baseline local share
    (("S","2026-08-10","D","D",59),("S","2026-08-10","A","D",41),("S","2026-08-17","D","D",10),("S","2026-08-17","A","D",90)),
    # insufficient baseline / observed
    (("S","2026-08-10","D","D",9),("S","2026-08-17","A","D",10)),
    (("S","2026-08-10","D","D",10),("S","2026-08-17","A","D",9)),
    # demand collapse
    (("S","2026-08-10","D","D",90),("S","2026-08-10","A","D",10),("S","2026-08-17","A","D",59)),
    # non-adjacent and one week
    (("S","2026-08-10","D","D",90),("S","2026-08-10","A","D",10),("S","2026-08-24","A","D",100)),
    (("S","2026-08-10","D","D",90),("S","2026-08-10","A","D",10)),
])
def test_false_positive_controls(rows):
    assert detect_stockouts(_profile(*rows)) == ()


def test_route_pattern_requires_drop_donor_rise_and_same_destination():
    too_small_drop = _profile(
        ("S","2026-08-10","D","D",80),("S","2026-08-10","A","D",20),
        ("S","2026-08-17","D","D",51),("S","2026-08-17","A","D",49),
    )
    no_donor_rise = _profile(
        ("S","2026-08-10","D","D",80),("S","2026-08-10","A","D",20),
        ("S","2026-08-17","D","D",40),("S","2026-08-17","A","D",39),
        ("S","2026-08-17","B","D",19),("S","2026-08-17","C","D",2),
    )
    donor_elsewhere = _profile(
        ("S","2026-08-10","D","D",80),("S","2026-08-10","A","D",20),
        ("S","2026-08-17","D","D",40),("S","2026-08-17","A","D",39),
        ("S","2026-08-17","B","D",19),("S","2026-08-17","C","D",2),
        ("S","2026-08-17","A","X",100),
    )
    assert detect_stockouts(too_small_drop) == ()
    assert detect_stockouts(no_donor_rise) == ()
    assert detect_stockouts(donor_elsewhere) == ()


def test_missing_observed_local_route_is_zero_not_missing():
    routes = _profile(("S","2026-08-10","D","D",90),("S","2026-08-10","A","D",10),
                      ("S","2026-08-17","A","D",100))
    assert detect_stockouts(routes)[0].observed_local_share == 0


def test_availability_only_corroborates_and_never_creates_or_erases():
    routes = _canonical()
    neutral = detect_stockouts(routes)
    assert neutral[0].historical_evidence_strength is SignalConfidence.HIGH
    assert neutral[0].route_cleaning_eligible is True
    assert neutral[0].confidence is SignalConfidence.HIGH
    assert neutral[0].availability_corroboration is AvailabilityCorroboration.NEUTRAL
    zero = detect_stockouts(routes, [AvailabilityRecord("SKU-1", "W", "Москва", 0)])
    assert zero[0].historical_evidence_strength is SignalConfidence.HIGH
    assert zero[0].route_cleaning_eligible is True
    assert zero[0].confidence is SignalConfidence.HIGH
    assert zero[0].availability_corroboration is AvailabilityCorroboration.SUPPORTS
    positive = detect_stockouts(routes, [AvailabilityRecord("SKU-1", "W", "Москва", 12)])
    assert positive[0].historical_evidence_strength is SignalConfidence.HIGH
    assert positive[0].route_cleaning_eligible is True
    assert positive[0].availability_corroboration is AvailabilityCorroboration.NEUTRAL
    assert positive[0].confidence is SignalConfidence.HIGH
    no_pattern = _profile(("S","2026-08-10","D","D",100),("S","2026-08-17","D","D",100))
    assert detect_stockouts(no_pattern, [AvailabilityRecord("S", "W", "D", 0)]) == ()


def test_multiple_destinations_aggregate_and_inconsistent_donor_is_rejected():
    extra = (
        ("SKU-1", "2026-08-10", "Тверь", "Тверь", 90),
        ("SKU-1", "2026-08-10", "Казань", "Тверь", 10),
        ("SKU-1", "2026-08-17", "Тверь", "Тверь", 20),
        ("SKU-1", "2026-08-17", "Казань", "Тверь", 80),
    )
    routes = _canonical(extra)
    signals = detect_stockouts(routes)
    distortion = detect_recommendation_distortion(signals, routes)[0]
    assert [e.destination_cluster_id for e in distortion.affected_destinations] == ["Москва", "Тверь"]
    assert "MULTIPLE_AFFECTED_DESTINATIONS" in distortion.explanation_codes
    fake = replace(signals[0], observed_week="2026-W35")
    assert detect_recommendation_distortion([fake], routes) == ()
    duplicate = detect_recommendation_distortion([signals[0], signals[0]], routes)[0]
    assert len(duplicate.affected_destinations) == 1
    assert "MULTIPLE_AFFECTED_DESTINATIONS" not in duplicate.explanation_codes


def test_contracts_and_thresholds_are_immutable_and_validated():
    signal = detect_stockouts(_canonical())[0]
    with pytest.raises(FrozenInstanceError):
        signal.sku = "changed"
    with pytest.raises(ValueError):
        StockoutThresholds(prior_local_share_min=Decimal("NaN"))
    with pytest.raises(ValueError):
        StockoutThresholds(min_fulfilled_weekly_quantity=True)
