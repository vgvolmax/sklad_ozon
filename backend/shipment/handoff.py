"""Resolve handoff evidence previously admitted by backend remote search."""

from dataclasses import dataclass

from backend.ozon.handoff import HandoffPoint, HandoffPointStore


@dataclass(frozen=True, slots=True)
class HandoffResolution:
    points: tuple[HandoffPoint, ...]
    reason_code: str | None


def resolve_handoff_points(
    store: HandoffPointStore, selected_ids: tuple[int, ...], *, required: bool = True,
) -> HandoffResolution:
    if not isinstance(store, HandoffPointStore):
        raise TypeError("handoff_store must be HandoffPointStore")
    if not required:
        return HandoffResolution((), None)
    if not selected_ids:
        return HandoffResolution((), "HANDOFF_POINT_REQUIRED")
    points = tuple(store.get(point_id) for point_id in selected_ids)
    if any(point is None or not point.warehouse_type for point in points):
        return HandoffResolution((), "HANDOFF_POINT_UNRESOLVED")
    return HandoffResolution(points, None)  # type: ignore[arg-type]
