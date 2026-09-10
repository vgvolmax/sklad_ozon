"""JSON request parsing for the thin shipment API boundary."""

from datetime import date

from .contracts import ShipmentMethod, ShipmentScenario


def parse_shipment_scenario(value: object) -> ShipmentScenario:
    if not isinstance(value, dict):
        raise ValueError("scenario must be an object")
    required = {
        "selected_cluster_ids", "date_from", "date_to", "allowed_methods",
        "preferred_clusters_per_shipment", "max_clusters_per_shipment",
    }
    if not required.issubset(value):
        raise ValueError("scenario fields are missing")
    clusters = value["selected_cluster_ids"]
    methods = value["allowed_methods"]
    handoffs = value.get("selected_handoff_point_ids", [])
    if not isinstance(clusters, list) or not isinstance(methods, list) or not isinstance(handoffs, list):
        raise ValueError("scenario collections must be arrays")
    try:
        return ShipmentScenario(
            tuple(clusters), date.fromisoformat(value["date_from"]),
            date.fromisoformat(value["date_to"]),
            tuple(ShipmentMethod(item) for item in methods),
            value["preferred_clusters_per_shipment"], value["max_clusters_per_shipment"],
            value.get("seller_warehouse_id"), tuple(handoffs),
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("invalid shipment scenario") from exc
