"""Daily locality and time-localized probable stockout/substitution episodes."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Iterable

from backend.domain.signals import AvailabilityCorroboration, SignalConfidence
from backend.ingestion.availability import AvailabilityRecord

from .daily import DailyOrderFacts

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class DailyOriginShare:
    origin_cluster_id: str
    quantity: int
    share: Decimal


@dataclass(frozen=True, slots=True)
class DailyLocalityPoint:
    sku: str
    destination_cluster_id: str
    day: date
    destination_demand_qty: int
    fulfilled_qty: int
    local_fulfilled_qty: int
    external_fulfilled_qty: int
    local_share: Decimal | None
    external_share: Decimal | None
    origin_shares: tuple[DailyOriginShare, ...]


@dataclass(frozen=True, slots=True)
class DailyStockoutThresholds:
    rolling_window_days: int = 7
    prior_local_share_min: Decimal = Decimal("0.60")
    local_share_drop_min: Decimal = Decimal("0.30")
    external_replacement_rise_min: Decimal = Decimal("0.20")
    min_fulfilled_window_quantity: int = 10
    demand_retention_min: Decimal = Decimal("0.60")
    min_contaminated_days: int = 2

    def __post_init__(self) -> None:
        rates = (self.prior_local_share_min, self.local_share_drop_min,
                 self.external_replacement_rise_min, self.demand_retention_min)
        if any(not isinstance(value, Decimal) or not value.is_finite()
               or not _ZERO <= value <= Decimal(1) for value in rates):
            raise ValueError("daily stockout rates must be finite Decimals between zero and one")
        integers = (self.rolling_window_days, self.min_fulfilled_window_quantity,
                    self.min_contaminated_days)
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
               for value in integers):
            raise ValueError("daily stockout integer thresholds must be positive integers")


class StockoutEpisodeScope(str, Enum):
    HISTORICAL_COMPLETE = "historical_complete"
    OPERATIONAL_CURRENT_WEEK = "operational_current_week"


@dataclass(frozen=True, slots=True)
class EpisodeReplacementOriginEvidence:
    origin_cluster_id: str
    baseline_share: Decimal
    peak_observed_share: Decimal
    max_share_increase: Decimal
    fulfilled_quantity_during_episode: int


@dataclass(frozen=True, slots=True)
class StockoutEpisode:
    sku: str
    destination_cluster_id: str
    start_date: date
    end_date: date
    affected_dates: tuple[date, ...]
    baseline_window_start: date
    baseline_window_end: date
    baseline_local_share: Decimal
    representative_local_share: Decimal
    destination_demand_retention: Decimal
    replacement_origins: tuple[EpisodeReplacementOriginEvidence, ...]
    historical_evidence_strength: SignalConfidence
    availability_corroboration: AvailabilityCorroboration
    confidence: SignalConfidence
    route_cleaning_eligible: bool
    evidence_scope: StockoutEpisodeScope
    reason_codes: tuple[str, ...]


def build_daily_locality_series(facts: DailyOrderFacts, as_of: date) -> tuple[DailyLocalityPoint, ...]:
    demand: dict[tuple[str, str, date], int] = defaultdict(int)
    origins: dict[tuple[str, str, date], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    first: dict[tuple[str, str], date] = {}
    for cell in facts.demand.cells:
        key = (cell.sku, cell.destination_cluster_id)
        demand[(key[0], key[1], cell.day)] += cell.quantity
        first[key] = min(first.get(key, cell.day), cell.day)
    for cell in facts.fulfillment.cells:
        key = (cell.sku, cell.destination_cluster_id)
        origins[(key[0], key[1], cell.day)][cell.origin_cluster_id] += cell.quantity
        first[key] = min(first.get(key, cell.day), cell.day)
    points = []
    for (sku, destination), earliest in sorted(first.items()):
        day = earliest
        while day <= as_of:
            origin_qty = origins.get((sku, destination, day), {})
            fulfilled = sum(origin_qty.values())
            local = origin_qty.get(destination, 0)
            if fulfilled:
                shares = tuple(DailyOriginShare(origin, quantity, Decimal(quantity) / Decimal(fulfilled))
                               for origin, quantity in sorted(origin_qty.items()))
                local_share = Decimal(local) / Decimal(fulfilled)
                external_share = Decimal(fulfilled - local) / Decimal(fulfilled)
            else:
                shares = ()
                local_share = external_share = None
            points.append(DailyLocalityPoint(
                sku, destination, day, demand.get((sku, destination, day), 0), fulfilled,
                local, fulfilled - local, local_share, external_share, shares,
            ))
            day += timedelta(days=1)
    return tuple(points)


@dataclass(frozen=True, slots=True)
class _Window:
    demand: int
    fulfilled: int
    local_share: Decimal
    origin_shares: dict[str, Decimal]


@dataclass(frozen=True, slots=True)
class _Candidate:
    sku: str
    destination: str
    affected: tuple[date, ...]
    baseline_start: date
    baseline_end: date
    baseline_local: Decimal
    observed_local: Decimal
    retention: Decimal
    scope: StockoutEpisodeScope
    donors: tuple[tuple[str, Decimal, Decimal, Decimal], ...]


def _window(points: list[DailyLocalityPoint]) -> _Window:
    fulfilled = sum(point.fulfilled_qty for point in points)
    local = sum(point.local_fulfilled_qty for point in points)
    quantities: dict[str, int] = defaultdict(int)
    for point in points:
        for origin in point.origin_shares:
            quantities[origin.origin_cluster_id] += origin.quantity
    return _Window(sum(point.destination_demand_qty for point in points), fulfilled,
                   Decimal(local) / Decimal(fulfilled) if fulfilled else _ZERO,
                   {origin: Decimal(qty) / Decimal(fulfilled)
                    for origin, qty in quantities.items()} if fulfilled else {})


def _availability(identity: tuple[str, str], rows: Iterable[AvailabilityRecord]) -> AvailabilityCorroboration:
    matching = [row for row in rows if (row.sku, row.cluster) == identity]
    if any(row.days_without_stock is not None and row.days_without_stock > 0 for row in matching):
        return AvailabilityCorroboration.SUPPORTS
    if (matching and any(row.days_without_stock == 0 for row in matching)
            and any(row.fbo_quantity is not None and row.fbo_quantity > 0 for row in matching)):
        return AvailabilityCorroboration.CONTRADICTS
    return AvailabilityCorroboration.NEUTRAL


def detect_stockout_episodes(
    locality: Iterable[DailyLocalityPoint],
    availability: Iterable[AvailabilityRecord] | None,
    as_of: date,
    thresholds: DailyStockoutThresholds = DailyStockoutThresholds(),
) -> tuple[StockoutEpisode, ...]:
    grouped: dict[tuple[str, str], list[DailyLocalityPoint]] = defaultdict(list)
    for point in locality:
        grouped[(point.sku, point.destination_cluster_id)].append(point)
    candidates: list[_Candidate] = []
    size = thresholds.rolling_window_days
    cutoff = as_of - timedelta(days=as_of.weekday() + 1)
    for (sku, destination), points in sorted(grouped.items()):
        points.sort(key=lambda point: point.day)
        for end in range(2 * size - 1, len(points)):
            baseline_points = points[end - 2 * size + 1:end - size + 1]
            observed_points = points[end - size + 1:end + 1]
            baseline, observed = _window(baseline_points), _window(observed_points)
            if (baseline.fulfilled < thresholds.min_fulfilled_window_quantity
                    or observed.fulfilled < thresholds.min_fulfilled_window_quantity
                    or baseline.local_share < thresholds.prior_local_share_min
                    or baseline.local_share - observed.local_share < thresholds.local_share_drop_min
                    or baseline.demand <= 0):
                continue
            retention = Decimal(observed.demand) / Decimal(baseline.demand)
            if retention < thresholds.demand_retention_min:
                continue
            donors = []
            for origin in sorted(set(baseline.origin_shares) | set(observed.origin_shares)):
                if origin == destination:
                    continue
                before = baseline.origin_shares.get(origin, _ZERO)
                after = observed.origin_shares.get(origin, _ZERO)
                increase = after - before
                if increase >= thresholds.external_replacement_rise_min:
                    donors.append((origin, before, after, increase))
            if not donors:
                continue
            affected = []
            for point in observed_points:
                if not point.fulfilled_qty or point.local_share is None:
                    continue
                if point.local_share > baseline.local_share - thresholds.local_share_drop_min:
                    continue
                if any(origin.origin_cluster_id != destination
                       and origin.share - baseline.origin_shares.get(origin.origin_cluster_id, _ZERO)
                       >= thresholds.external_replacement_rise_min
                       for origin in point.origin_shares):
                    affected.append(point.day)
            if len(set(affected)) < thresholds.min_contaminated_days:
                continue
            scope = (StockoutEpisodeScope.HISTORICAL_COMPLETE
                     if points[end].day <= cutoff else StockoutEpisodeScope.OPERATIONAL_CURRENT_WEEK)
            candidates.append(_Candidate(sku, destination, tuple(sorted(set(affected))),
                                         baseline_points[0].day, baseline_points[-1].day,
                                         baseline.local_share, observed.local_share, retention,
                                         scope, tuple(donors)))

    rows = tuple(availability or ())
    by_key: dict[tuple[str, str, StockoutEpisodeScope], list[_Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_key[(candidate.sku, candidate.destination, candidate.scope)].append(candidate)
    episodes = []
    point_index = {(p.sku, p.destination_cluster_id, p.day): p
                   for points in grouped.values() for p in points}
    for key, values in sorted(by_key.items(), key=lambda item: (item[0][0], item[0][1], item[0][2].value)):
        values.sort(key=lambda item: (item.affected[0], item.baseline_start))
        merged: list[list[_Candidate]] = []
        for candidate in values:
            if merged and min(candidate.affected) <= max(d for c in merged[-1] for d in c.affected) + timedelta(days=1):
                merged[-1].append(candidate)
            else:
                merged.append([candidate])
        for group in merged:
            earliest = min(group, key=lambda item: (item.baseline_start, item.baseline_end))
            affected = tuple(sorted({day for candidate in group for day in candidate.affected}))
            donor_ids = {donor[0] for candidate in group for donor in candidate.donors}
            donor_evidence = []
            for origin in donor_ids:
                entries = [donor for candidate in group for donor in candidate.donors if donor[0] == origin]
                quantity = sum(next((share.quantity for share in point_index[(key[0], key[1], day)].origin_shares
                                     if share.origin_cluster_id == origin), 0) for day in affected)
                donor_evidence.append(EpisodeReplacementOriginEvidence(
                    origin, next((d[1] for d in earliest.donors if d[0] == origin), _ZERO),
                    max(d[2] for d in entries), max(d[3] for d in entries), quantity))
            donor_evidence.sort(key=lambda item: (-item.max_share_increase, item.origin_cluster_id))
            corroboration = _availability((key[0], key[1]), rows)
            historical = (SignalConfidence.HIGH if key[2] is StockoutEpisodeScope.HISTORICAL_COMPLETE
                          else SignalConfidence.MEDIUM)
            confidence = (SignalConfidence.HIGH if historical is SignalConfidence.HIGH
                          or corroboration is AvailabilityCorroboration.SUPPORTS else historical)
            codes = ["BASELINE_LOCAL_SHARE_HIGH", "LOCAL_SHARE_DROP",
                     "EXTERNAL_REPLACEMENT_RISE", "DEMAND_RETAINED",
                     "SUSTAINED_DAILY_CONTAMINATION"]
            if corroboration is AvailabilityCorroboration.SUPPORTS:
                codes.append("RECENT_DAYS_WITHOUT_STOCK")
            elif corroboration is AvailabilityCorroboration.CONTRADICTS:
                codes.append("CURRENT_AVAILABILITY_CONTRADICTS")
            if key[2] is StockoutEpisodeScope.OPERATIONAL_CURRENT_WEEK:
                codes.append("CURRENT_WEEK_OPERATIONAL_EVIDENCE")
            episodes.append(StockoutEpisode(
                key[0], key[1], affected[0], affected[-1], affected,
                earliest.baseline_start, earliest.baseline_end, earliest.baseline_local,
                min(c.observed_local for c in group), min(c.retention for c in group),
                tuple(donor_evidence), historical, corroboration, confidence,
                key[2] is StockoutEpisodeScope.HISTORICAL_COMPLETE, key[2], tuple(codes)))
    return tuple(sorted(episodes, key=lambda item: (item.sku, item.destination_cluster_id,
                                                    item.start_date, item.end_date)))
