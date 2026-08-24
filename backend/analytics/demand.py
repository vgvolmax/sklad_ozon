"""Weekly net demand attributed strictly to customer destinations."""

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from backend.domain.contracts import OrderRecord
from backend.domain.invariants import is_net_demand, validate_order

from ._weeks import (
    AnalyticsWindow,
    WeekPolicy,
    make_window,
    parse_source_date,
    require_completed_iso_weeks,
)


@dataclass(frozen=True, slots=True)
class DemandCell:
    sku: str
    iso_year: int
    iso_week: int
    destination_cluster_id: str
    quantity: int
    observation_count: int


@dataclass(frozen=True, slots=True)
class DemandResult:
    cells: tuple[DemandCell, ...]
    window: AnalyticsWindow


def aggregate_demand(
    orders: Iterable[OrderRecord],
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> DemandResult:
    require_completed_iso_weeks(week_policy)
    current_week = as_of.isocalendar()[:2]
    totals: dict[tuple[int, int, str, str], list[int]] = {}
    included_weeks: set[tuple[int, int]] = set()
    excluded_current = excluded_future = excluded_undated = 0

    for order in orders:
        validate_order(order)
        if not is_net_demand(order):
            continue
        event_date = parse_source_date(order.accepted_at)
        if event_date is None:
            excluded_undated += 1
            continue
        if event_date > as_of:
            excluded_future += 1
            continue
        iso = event_date.isocalendar()
        week = (iso.year, iso.week)
        if week == current_week:
            excluded_current += 1
            continue
        included_weeks.add(week)
        key = (iso.year, iso.week, order.sku, order.destination_cluster)
        aggregate = totals.setdefault(key, [0, 0])
        aggregate[0] += order.quantity
        aggregate[1] += 1

    cells = tuple(
        DemandCell(
            sku=sku,
            iso_year=year,
            iso_week=week,
            destination_cluster_id=destination,
            quantity=quantity,
            observation_count=count,
        )
        for (year, week, sku, destination), (quantity, count) in sorted(totals.items())
    )
    return DemandResult(
        cells=cells,
        window=make_window(
            as_of=as_of,
            included_weeks=included_weeks,
            excluded_current=excluded_current,
            excluded_future=excluded_future,
            excluded_undated=excluded_undated,
        ),
    )
