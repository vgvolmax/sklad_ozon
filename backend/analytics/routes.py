"""Weekly observed fulfilled routes from physical origins to destinations."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from backend.domain.contracts import OrderRecord
from backend.domain.invariants import is_fulfilled_route, validate_order

from ._weeks import (
    AnalyticsWindow,
    WeekPolicy,
    make_window,
    parse_source_date,
    require_completed_iso_weeks,
)


@dataclass(frozen=True, slots=True)
class RouteCell:
    sku: str
    iso_year: int
    iso_week: int
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    observation_count: int
    share_of_destination: Decimal
    share_of_origin: Decimal


@dataclass(frozen=True, slots=True)
class RouteProfile:
    routes: tuple[RouteCell, ...]
    window: AnalyticsWindow


def build_route_profile(
    orders: Iterable[OrderRecord],
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> RouteProfile:
    require_completed_iso_weeks(week_policy)
    current_week = as_of.isocalendar()[:2]
    totals: dict[tuple[int, int, str, str, str], list[int]] = {}
    included_weeks: set[tuple[int, int]] = set()
    excluded_current = excluded_future = excluded_undated = 0

    for order in orders:
        validate_order(order)
        if not is_fulfilled_route(order):
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
        key = (iso.year, iso.week, order.sku,
               order.origin_cluster, order.destination_cluster)
        aggregate = totals.setdefault(key, [0, 0])
        aggregate[0] += order.quantity
        aggregate[1] += 1

    destination_totals: dict[tuple[int, int, str, str], int] = {}
    origin_totals: dict[tuple[int, int, str, str], int] = {}
    for (year, week, sku, origin, destination), (quantity, _) in totals.items():
        destination_key = (year, week, sku, destination)
        origin_key = (year, week, sku, origin)
        destination_totals[destination_key] = destination_totals.get(destination_key, 0) + quantity
        origin_totals[origin_key] = origin_totals.get(origin_key, 0) + quantity

    routes = tuple(
        RouteCell(
            sku=sku,
            iso_year=year,
            iso_week=week,
            origin_cluster_id=origin,
            destination_cluster_id=destination,
            quantity=quantity,
            observation_count=count,
            share_of_destination=(
                Decimal(quantity) / Decimal(destination_totals[(year, week, sku, destination)])
            ),
            share_of_origin=(
                Decimal(quantity) / Decimal(origin_totals[(year, week, sku, origin)])
            ),
        )
        for (year, week, sku, origin, destination), (quantity, count)
        in sorted(totals.items())
        if quantity > 0
    )
    return RouteProfile(
        routes=routes,
        window=make_window(
            as_of=as_of,
            included_weeks=included_weeks,
            excluded_current=excluded_current,
            excluded_future=excluded_future,
            excluded_undated=excluded_undated,
        ),
    )
