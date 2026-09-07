"""Canonical daily destination-demand and fulfillment facts."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from backend.domain.contracts import OrderRecord
from backend.domain.invariants import is_fulfilled_route, is_net_demand, validate_order

from ._weeks import parse_source_date


@dataclass(frozen=True, slots=True)
class DailyDemandCell:
    sku: str
    day: date
    destination_cluster_id: str
    quantity: int
    observation_count: int


@dataclass(frozen=True, slots=True)
class DailyFulfillmentCell:
    sku: str
    day: date
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    observation_count: int


@dataclass(frozen=True, slots=True)
class DailyDemandResult:
    cells: tuple[DailyDemandCell, ...]
    excluded_future_observations: int
    excluded_undated_observations: int


@dataclass(frozen=True, slots=True)
class DailyFulfillmentResult:
    cells: tuple[DailyFulfillmentCell, ...]
    excluded_future_observations: int
    excluded_undated_observations: int


@dataclass(frozen=True, slots=True)
class DailyOrderFacts:
    demand: DailyDemandResult
    fulfillment: DailyFulfillmentResult


def build_daily_order_facts(
    orders: Iterable[OrderRecord],
    as_of: date,
) -> DailyOrderFacts:
    demand_totals: dict[tuple[date, str, str], list[int]] = defaultdict(lambda: [0, 0])
    fulfillment_totals: dict[tuple[date, str, str, str], list[int]] = defaultdict(
        lambda: [0, 0]
    )
    demand_future = demand_undated = 0
    fulfillment_future = fulfillment_undated = 0

    for order in orders:
        validate_order(order)
        demand_eligible = is_net_demand(order)
        fulfillment_eligible = is_fulfilled_route(order)
        if not demand_eligible and not fulfillment_eligible:
            continue

        event_date = parse_source_date(order.accepted_at)
        if event_date is None:
            if demand_eligible:
                demand_undated += 1
            if fulfillment_eligible:
                fulfillment_undated += 1
            continue
        if event_date > as_of:
            if demand_eligible:
                demand_future += 1
            if fulfillment_eligible:
                fulfillment_future += 1
            continue

        if demand_eligible:
            aggregate = demand_totals[(event_date, order.sku, order.destination_cluster)]
            aggregate[0] += order.quantity
            aggregate[1] += 1
        if fulfillment_eligible:
            aggregate = fulfillment_totals[(
                event_date,
                order.sku,
                order.origin_cluster,
                order.destination_cluster,
            )]
            aggregate[0] += order.quantity
            aggregate[1] += 1

    demand_cells = tuple(
        DailyDemandCell(sku, day, destination, quantity, count)
        for (day, sku, destination), (quantity, count) in sorted(demand_totals.items())
    )
    fulfillment_cells = tuple(
        DailyFulfillmentCell(sku, day, origin, destination, quantity, count)
        for (day, sku, origin, destination), (quantity, count)
        in sorted(fulfillment_totals.items())
    )
    return DailyOrderFacts(
        DailyDemandResult(demand_cells, demand_future, demand_undated),
        DailyFulfillmentResult(
            fulfillment_cells, fulfillment_future, fulfillment_undated
        ),
    )
