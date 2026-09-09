"""Explicit remote handoff search and restart-ephemeral identity store."""

from dataclasses import dataclass

from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import HANDOFF_SEARCH_PATH


@dataclass(frozen=True, slots=True)
class HandoffPoint:
    warehouse_id: int
    name: str | None
    address: str | None
    warehouse_type: str | None
    point_type: str | None


class HandoffPointStore:
    def __init__(self) -> None:
        self._points: dict[int, HandoffPoint] = {}

    def put_all(self, points: tuple[HandoffPoint, ...]) -> None:
        self._points.update((point.warehouse_id, point) for point in points)

    def get(self, warehouse_id: int) -> HandoffPoint | None:
        return self._points.get(warehouse_id)

    def require(self, warehouse_id: int) -> HandoffPoint:
        try:
            return self._points[warehouse_id]
        except KeyError:
            raise KeyError(f"Unresolved handoff point {warehouse_id}") from None


def search_handoff_points(client: OzonClient, query: str, supply_types: tuple[str, ...]) -> tuple[HandoffPoint, ...]:
    query = query.strip()
    if len(query) < 4:
        raise ValueError("query must contain at least 4 trimmed characters")
    response = client.post_json(HANDOFF_SEARCH_PATH, {"search":query,"supply_types":list(supply_types)},
                                policy=OzonRequestPolicy(retry_safe=True))
    result = response.get("result", response)
    items = result.get("warehouses", result.get("items", [])) if isinstance(result, dict) else []
    points = []
    for raw in items:
        try:
            point = HandoffPoint(
                int(raw.get("warehouse_id", raw.get("id"))),
                str(raw.get("name")).strip() if raw.get("name") is not None else None,
                str(raw.get("address")).strip() if raw.get("address") is not None else None,
                str(raw.get("warehouse_type")).strip() if raw.get("warehouse_type") is not None else None,
                str(raw.get("point_type")).strip() if raw.get("point_type") is not None else None,
            )
        except (TypeError, ValueError):
            continue
        points.append(point)
    return tuple(points)
