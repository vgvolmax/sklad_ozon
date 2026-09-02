"""Auditable historical route distributions with stockout intervals removed."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
import re
from typing import Iterable

from backend.domain.signals import SignalConfidence, StockoutSignal

from .routes import RouteCell, RouteProfile


_WEEK_PATTERN = re.compile(r"^(\d{4})-W(\d{2})$")
_CONFIDENCE_RANK = {
    SignalConfidence.LOW: 0,
    SignalConfidence.MEDIUM: 1,
    SignalConfidence.HIGH: 2,
}


class CleanRouteFallbackStatus(str, Enum):
    CLEAN_AVAILABLE = "clean_available"
    OBSERVED_FALLBACK = "observed_fallback"


@dataclass(frozen=True, slots=True)
class CleanRoutePolicy:
    """Deprecated compatibility settings; eligibility controls exclusions."""

    minimum_exclusion_confidence: SignalConfidence = SignalConfidence.HIGH


@dataclass(frozen=True, slots=True)
class RouteDistributionCell:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    observation_count: int
    share: Decimal


@dataclass(frozen=True, slots=True)
class ExcludedRouteEvidence:
    sku: str
    iso_year: int
    iso_week: int
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    observation_count: int
    stockout_confidence: SignalConfidence
    stockout_observed_week: str


@dataclass(frozen=True, slots=True)
class RouteProfileSummary:
    sku: str
    origin_cluster_id: str
    observed_total_quantity: int
    observed_observation_count: int
    clean_total_quantity: int
    clean_observation_count: int
    excluded_quantity: int
    excluded_observation_count: int
    observed_share_sum: Decimal
    clean_share_sum: Decimal | None
    fallback_status: CleanRouteFallbackStatus


@dataclass(frozen=True, slots=True)
class CleanRouteResult:
    observed_routes: tuple[RouteDistributionCell, ...]
    clean_routes: tuple[RouteDistributionCell, ...]
    excluded_routes: tuple[ExcludedRouteEvidence, ...]
    summaries: tuple[RouteProfileSummary, ...]


def _parse_week(observed_week: str) -> tuple[int, int]:
    match = _WEEK_PATTERN.fullmatch(observed_week)
    if match is None:
        raise ValueError(f"invalid stockout observed_week: {observed_week!r}")
    year, week = map(int, match.groups())
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise ValueError(f"invalid stockout observed_week: {observed_week!r}") from exc
    return year, week


def _aggregate(routes: Iterable[RouteCell]) -> tuple[RouteDistributionCell, ...]:
    totals: dict[tuple[str, str, str], list[int]] = {}
    origin_totals: dict[tuple[str, str], int] = {}
    for route in routes:
        key = (route.sku, route.origin_cluster_id, route.destination_cluster_id)
        aggregate = totals.setdefault(key, [0, 0])
        aggregate[0] += route.quantity
        aggregate[1] += route.observation_count
        origin_key = (route.sku, route.origin_cluster_id)
        origin_totals[origin_key] = origin_totals.get(origin_key, 0) + route.quantity
    return tuple(
        RouteDistributionCell(
            sku=sku,
            origin_cluster_id=origin,
            destination_cluster_id=destination,
            quantity=quantity,
            observation_count=count,
            share=Decimal(quantity) / Decimal(origin_totals[(sku, origin)]),
        )
        for (sku, origin, destination), (quantity, count) in sorted(totals.items())
    )


def build_clean_route_profile(
    observed: RouteProfile,
    stockouts: Iterable[StockoutSignal],
    policy: CleanRoutePolicy = CleanRoutePolicy(),
) -> CleanRouteResult:
    """Derive clean history without changing the weekly observed profile."""
    included_weeks = set(observed.window.included_weeks)
    for route in observed.routes:
        if (route.iso_year, route.iso_week) not in included_weeks:
            raise ValueError(
                "RouteProfile route week is absent from window.included_weeks"
            )

    signals: dict[tuple[str, str, int, int], tuple[SignalConfidence, str]] = {}
    for signal in stockouts:
        year, week = _parse_week(signal.observed_week)
        if not signal.route_cleaning_eligible:
            continue
        key = (signal.sku, signal.destination_cluster_id, year, week)
        previous = signals.get(key)
        if previous is None or _CONFIDENCE_RANK[signal.confidence] > _CONFIDENCE_RANK[previous[0]]:
            signals[key] = (signal.confidence, signal.observed_week)

    clean_weekly: list[RouteCell] = []
    excluded: list[ExcludedRouteEvidence] = []
    for route in observed.routes:
        identity = (
            route.sku,
            route.destination_cluster_id,
            route.iso_year,
            route.iso_week,
        )
        signal = signals.get(identity)
        if signal is not None:
            excluded.append(
                ExcludedRouteEvidence(
                    sku=route.sku,
                    iso_year=route.iso_year,
                    iso_week=route.iso_week,
                    origin_cluster_id=route.origin_cluster_id,
                    destination_cluster_id=route.destination_cluster_id,
                    quantity=route.quantity,
                    observation_count=route.observation_count,
                    stockout_confidence=signal[0],
                    stockout_observed_week=signal[1],
                )
            )
        else:
            clean_weekly.append(route)

    observed_routes = _aggregate(observed.routes)
    clean_routes = _aggregate(clean_weekly)
    observed_by_origin = _origin_totals(observed_routes)
    clean_by_origin = _origin_totals(clean_routes)
    excluded_by_origin = _evidence_totals(excluded)
    summaries = tuple(
        RouteProfileSummary(
            sku=sku,
            origin_cluster_id=origin,
            observed_total_quantity=observed_by_origin[(sku, origin)][0],
            observed_observation_count=observed_by_origin[(sku, origin)][1],
            clean_total_quantity=clean_by_origin.get((sku, origin), (0, 0))[0],
            clean_observation_count=clean_by_origin.get((sku, origin), (0, 0))[1],
            excluded_quantity=excluded_by_origin.get((sku, origin), (0, 0))[0],
            excluded_observation_count=excluded_by_origin.get((sku, origin), (0, 0))[1],
            observed_share_sum=sum(
                (cell.share for cell in observed_routes
                 if (cell.sku, cell.origin_cluster_id) == (sku, origin)),
                Decimal(0),
            ),
            clean_share_sum=(
                sum(
                    (cell.share for cell in clean_routes
                     if (cell.sku, cell.origin_cluster_id) == (sku, origin)),
                    Decimal(0),
                )
                if (sku, origin) in clean_by_origin else None
            ),
            fallback_status=(
                CleanRouteFallbackStatus.CLEAN_AVAILABLE
                if (sku, origin) in clean_by_origin
                else CleanRouteFallbackStatus.OBSERVED_FALLBACK
            ),
        )
        for sku, origin in sorted(observed_by_origin)
    )
    return CleanRouteResult(
        observed_routes=observed_routes,
        clean_routes=clean_routes,
        excluded_routes=tuple(sorted(
            excluded,
            key=lambda row: (
                row.iso_year, row.iso_week, row.sku,
                row.destination_cluster_id, row.origin_cluster_id,
            ),
        )),
        summaries=summaries,
    )


def _origin_totals(
    routes: Iterable[RouteDistributionCell],
) -> dict[tuple[str, str], tuple[int, int]]:
    totals: dict[tuple[str, str], list[int]] = {}
    for route in routes:
        aggregate = totals.setdefault((route.sku, route.origin_cluster_id), [0, 0])
        aggregate[0] += route.quantity
        aggregate[1] += route.observation_count
    return {key: (value[0], value[1]) for key, value in totals.items()}


def _evidence_totals(
    evidence: Iterable[ExcludedRouteEvidence],
) -> dict[tuple[str, str], tuple[int, int]]:
    totals: dict[tuple[str, str], list[int]] = {}
    for row in evidence:
        aggregate = totals.setdefault((row.sku, row.origin_cluster_id), [0, 0])
        aggregate[0] += row.quantity
        aggregate[1] += row.observation_count
    return {key: (value[0], value[1]) for key, value in totals.items()}
