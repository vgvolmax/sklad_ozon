"""Canonical local method and placement compatibility rules."""

from backend.supply.contracts import PlacementZoneKind, ShippableLine

from .contracts import METHOD_RULES, ShipmentMethod


def placement_reason(line: ShippableLine, method: ShipmentMethod) -> str | None:
    """Return a conservative blocking reason without reconstructing evidence."""
    if line.placement_zone_kind is PlacementZoneKind.UNKNOWN or not line.placement_zones:
        return "PLACEMENT_ZONE_INCOMPLETE"
    normalized = {zone.strip().upper() for zone in line.placement_zones}
    if method is ShipmentMethod.PVZ_CROSSDOCK and any(
            token in zone for zone in normalized for token in ("KGT", "КГТ")):
        return "PLACEMENT_ZONE_UNSUPPORTED"
    return None


def method_cluster_limit(method: ShipmentMethod, user_max: int) -> int:
    return min(user_max, METHOD_RULES[method].hard_max_clusters)
