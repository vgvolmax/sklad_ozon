"""Pure demand and fulfilled-route analytics."""

from ._weeks import AnalyticsWindow, WeekPolicy
from .demand import DemandCell, DemandResult, aggregate_demand
from .routes import RouteCell, RouteProfile, build_route_profile

__all__ = (
    "AnalyticsWindow",
    "DemandCell",
    "DemandResult",
    "RouteCell",
    "RouteProfile",
    "WeekPolicy",
    "aggregate_demand",
    "build_route_profile",
)
