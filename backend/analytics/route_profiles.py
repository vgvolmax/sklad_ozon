"""Auditable selection of the best available route distribution."""

from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from backend.domain.signals import SignalConfidence
from backend.economics.tariffs import RouteProfileSource

from .clean_routes import CleanRouteResult, RouteDistributionCell
from .routes import RouteProfile


@dataclass(frozen=True, slots=True)
class RouteProfileSelection:
    sku: str
    origin_cluster_id: str
    source: RouteProfileSource
    sample_quantity: int
    sample_observation_count: int
    confidence: SignalConfidence
    profile: tuple[RouteDistributionCell, ...]


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str")
    if not value.strip():
        raise ValueError(f"{name} must be nonblank")
    return value


def _selection(sku, origin, source, confidence, populations):
    totals: dict[str, list[int]] = {}
    for destination, quantity, count in populations:
        aggregate = totals.setdefault(destination, [0, 0])
        aggregate[0] += quantity
        aggregate[1] += count
    quantity = sum(values[0] for values in totals.values())
    count = sum(values[1] for values in totals.values())
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        profile = tuple(
            RouteDistributionCell(sku, origin, destination, values[0], values[1],
                                  Decimal(values[0]) / Decimal(quantity))
            for destination, values in sorted(totals.items()) if values[0] > 0
        ) if quantity else ()
    return RouteProfileSelection(sku, origin, source, quantity, count, confidence, profile)


def select_route_profile(
    sku: str,
    origin_cluster_id: str,
    clean: CleanRouteResult,
    observed: RouteProfile,
) -> RouteProfileSelection:
    """Select CLEAN, exact observed, origin-wide, then global history."""
    sku = _identity(sku, "sku")
    origin_cluster_id = _identity(origin_cluster_id, "origin_cluster_id")
    exact_clean = tuple(sorted(
        (cell for cell in clean.clean_routes
         if cell.sku == sku and cell.origin_cluster_id == origin_cluster_id),
        key=lambda cell: cell.destination_cluster_id,
    ))
    if exact_clean:
        return RouteProfileSelection(
            sku, origin_cluster_id, RouteProfileSource.CLEAN,
            sum(cell.quantity for cell in exact_clean),
            sum(cell.observation_count for cell in exact_clean),
            SignalConfidence.HIGH, exact_clean,
        )

    exact = [route for route in observed.routes
             if route.sku == sku and route.origin_cluster_id == origin_cluster_id]
    if exact:
        return _selection(sku, origin_cluster_id, RouteProfileSource.OBSERVED,
                          SignalConfidence.MEDIUM,
                          ((r.destination_cluster_id, r.quantity, r.observation_count) for r in exact))
    origin = [route for route in observed.routes
              if route.origin_cluster_id == origin_cluster_id]
    if origin:
        return _selection(sku, origin_cluster_id, RouteProfileSource.ORIGIN_ALL_SKUS,
                          SignalConfidence.LOW,
                          ((r.destination_cluster_id, r.quantity, r.observation_count) for r in origin))
    return _selection(sku, origin_cluster_id, RouteProfileSource.GLOBAL,
                      SignalConfidence.LOW,
                      ((r.destination_cluster_id, r.quantity, r.observation_count)
                       for r in observed.routes))
