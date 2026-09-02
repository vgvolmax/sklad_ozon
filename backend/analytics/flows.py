"""Fulfillment-flow aggregates preserving physical route direction."""

from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from typing import Iterable

from .clean_routes import CleanRouteResult, RouteDistributionCell
from .routes import RouteCell, RouteProfile


@dataclass(frozen=True, slots=True)
class FulfillmentFlowCell:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    destination_share: Decimal
    observation_count: int


def _aggregate(rows: Iterable[RouteCell | RouteDistributionCell]) -> tuple[FulfillmentFlowCell, ...]:
    totals: dict[tuple[str, str, str], list[int]] = {}
    for row in rows:
        aggregate = totals.setdefault(
            (row.sku, row.origin_cluster_id, row.destination_cluster_id), [0, 0]
        )
        aggregate[0] += row.quantity
        aggregate[1] += row.observation_count
    denominators: dict[tuple[str, str], int] = {}
    for (sku, _, destination), (quantity, _) in totals.items():
        key = (sku, destination)
        denominators[key] = denominators.get(key, 0) + quantity
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        return tuple(
            FulfillmentFlowCell(
                sku, origin, destination, quantity,
                Decimal(quantity) / Decimal(denominators[(sku, destination)]), count,
            )
            for (sku, origin, destination), (quantity, count) in sorted(
                totals.items(), key=lambda item: (item[0][0], item[0][2], item[0][1])
            )
            if quantity > 0
        )


def aggregate_observed_flows(observed: RouteProfile) -> tuple[FulfillmentFlowCell, ...]:
    return _aggregate(observed.routes)


def aggregate_clean_flows(clean: CleanRouteResult) -> tuple[FulfillmentFlowCell, ...]:
    return _aggregate(clean.clean_routes)
