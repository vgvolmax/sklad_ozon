"""Weekly net demand attributed strictly to customer destinations."""

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from backend.domain.contracts import OrderRecord

from .daily import DailyDemandResult, build_daily_order_facts

from ._weeks import (
    AnalyticsWindow,
    WeekPolicy,
    make_window,
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


def aggregate_weekly_demand(
    daily: DailyDemandResult,
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> DemandResult:
    require_completed_iso_weeks(week_policy)
    current_week = as_of.isocalendar()[:2]
    totals: dict[tuple[int, int, str, str], list[int]] = {}
    included_weeks: set[tuple[int, int]] = set()
    excluded_current = 0

    for cell in daily.cells:
        iso = cell.day.isocalendar()
        week = (iso.year, iso.week)
        if week == current_week:
            excluded_current += cell.observation_count
            continue
        included_weeks.add(week)
        key = (iso.year, iso.week, cell.sku, cell.destination_cluster_id)
        aggregate = totals.setdefault(key, [0, 0])
        aggregate[0] += cell.quantity
        aggregate[1] += cell.observation_count

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
            excluded_future=daily.excluded_future_observations,
            excluded_undated=daily.excluded_undated_observations,
        ),
    )


def aggregate_demand(
    orders: Iterable[OrderRecord],
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> DemandResult:
    daily = build_daily_order_facts(orders, as_of)
    return aggregate_weekly_demand(daily.demand, as_of, week_policy)
