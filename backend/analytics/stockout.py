"""Detect probable destination stockouts from completed-week route shifts."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from backend.analytics.routes import RouteProfile
from backend.domain.signals import (
    AvailabilityCorroboration,
    ReplacementOriginEvidence,
    SignalConfidence,
    StockoutSignal,
)
from backend.ingestion.availability import AvailabilityRecord


@dataclass(frozen=True, slots=True)
class StockoutThresholds:
    prior_local_share_min: Decimal = Decimal("0.60")
    local_share_drop_min: Decimal = Decimal("0.30")
    external_replacement_rise_min: Decimal = Decimal("0.20")
    min_fulfilled_weekly_quantity: int = 10
    demand_retention_min: Decimal = Decimal("0.60")

    def __post_init__(self) -> None:
        rates = (
            self.prior_local_share_min,
            self.local_share_drop_min,
            self.external_replacement_rise_min,
            self.demand_retention_min,
        )
        if any(not isinstance(rate, Decimal) or not rate.is_finite() or not Decimal(0) <= rate <= Decimal(1) for rate in rates):
            raise ValueError("stockout rates must be finite Decimals between zero and one")
        if isinstance(self.min_fulfilled_weekly_quantity, bool) or not isinstance(self.min_fulfilled_weekly_quantity, int) or self.min_fulfilled_weekly_quantity <= 0:
            raise ValueError("minimum fulfilled weekly quantity must be a positive integer")


@dataclass(frozen=True, slots=True)
class _Metrics:
    quantity: int
    local_share: Decimal
    origin_shares: dict[str, Decimal]


def _week_id(year: int, week: int) -> str:
    return f"{year:04d}-W{week:02d}"


def _metrics(profile: RouteProfile) -> dict[tuple[str, str, int, int], _Metrics]:
    quantities: dict[tuple[str, str, int, int], dict[str, int]] = {}
    eligible_weeks = set(profile.window.included_weeks)
    for route in profile.routes:
        if (route.iso_year, route.iso_week) not in eligible_weeks:
            continue
        key = (route.sku, route.destination_cluster_id, route.iso_year, route.iso_week)
        origins = quantities.setdefault(key, {})
        origins[route.origin_cluster_id] = origins.get(route.origin_cluster_id, 0) + route.quantity
    result = {}
    for key, origins in quantities.items():
        total = sum(origins.values())
        destination = key[1]
        result[key] = _Metrics(
            total,
            Decimal(origins.get(destination, 0)) / Decimal(total),
            {origin: Decimal(quantity) / Decimal(total) for origin, quantity in origins.items()},
        )
    return result


def _display_confidence(
    historical: SignalConfidence,
    corroboration: AvailabilityCorroboration,
) -> SignalConfidence:
    if historical is SignalConfidence.HIGH:
        return SignalConfidence.HIGH
    if corroboration is AvailabilityCorroboration.SUPPORTS:
        return SignalConfidence.HIGH
    return historical


def detect_stockouts(
    weekly_profiles: RouteProfile,
    availability: Iterable[AvailabilityRecord] | None = None,
    thresholds: StockoutThresholds = StockoutThresholds(),
) -> tuple[StockoutSignal, ...]:
    """Return route-pattern hypotheses; current availability only corroborates."""
    availability_support: set[tuple[str, str]] = set()
    for record in availability or ():
        key = (record.sku, record.cluster)
        if record.days_without_stock is not None and record.days_without_stock > 0:
            availability_support.add(key)

    metrics = _metrics(weekly_profiles)
    grouped: dict[tuple[str, str], list[tuple[int, int, _Metrics]]] = {}
    for (sku, destination, year, week), value in metrics.items():
        grouped.setdefault((sku, destination), []).append((year, week, value))

    signals = []
    for (sku, destination), weeks in sorted(grouped.items()):
        weeks.sort(key=lambda item: date.fromisocalendar(item[0], item[1], 1))
        for baseline, observed in zip(weeks, weeks[1:]):
            before_date = date.fromisocalendar(baseline[0], baseline[1], 1)
            after_date = date.fromisocalendar(observed[0], observed[1], 1)
            if after_date - before_date != timedelta(days=7):
                continue
            before, after = baseline[2], observed[2]
            retention = Decimal(after.quantity) / Decimal(before.quantity)
            if (before.quantity < thresholds.min_fulfilled_weekly_quantity
                    or after.quantity < thresholds.min_fulfilled_weekly_quantity
                    or before.local_share < thresholds.prior_local_share_min
                    or before.local_share - after.local_share < thresholds.local_share_drop_min
                    or retention < thresholds.demand_retention_min):
                continue
            replacements = []
            for origin in set(before.origin_shares) | set(after.origin_shares):
                if origin == destination:
                    continue
                share_before = before.origin_shares.get(origin, Decimal(0))
                share_after = after.origin_shares.get(origin, Decimal(0))
                if share_after - share_before >= thresholds.external_replacement_rise_min:
                    replacements.append(ReplacementOriginEvidence(origin, share_before, share_after))
            replacements.sort(key=lambda item: (-(item.share_after - item.share_before), item.origin_cluster_id))
            if not replacements:
                continue
            historical_evidence_strength = SignalConfidence.HIGH
            route_cleaning_eligible = True
            corroboration = (AvailabilityCorroboration.SUPPORTS
                              if (sku, destination) in availability_support
                              else AvailabilityCorroboration.NEUTRAL)
            codes = ["BASELINE_LOCAL_SHARE_HIGH", "LOCAL_SHARE_DROP", "EXTERNAL_REPLACEMENT_RISE", "DEMAND_RETAINED"]
            if corroboration is AvailabilityCorroboration.SUPPORTS:
                codes.append("RECENT_DAYS_WITHOUT_STOCK")
            signals.append(StockoutSignal(
                sku, destination,
                historical_evidence_strength,
                route_cleaning_eligible,
                _display_confidence(historical_evidence_strength, corroboration),
                _week_id(baseline[0], baseline[1]), _week_id(observed[0], observed[1]),
                before.local_share, after.local_share, retention, corroboration,
                tuple(replacements), tuple(codes),
            ))
    return tuple(signals)
