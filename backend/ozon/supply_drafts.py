"""Current Ozon wire mapping for method-specific temporary drafts."""

from dataclasses import dataclass

from backend.shipment.contracts import CandidateShipment, ShipmentMethod
from .client import OzonRequestPolicy
from .endpoints import DRAFT_CROSSDOCK_CREATE, DRAFT_DIRECT_CREATE, DRAFT_MULTI_CLUSTER_CREATE
from .source_contracts import Cluster

CREATE_POLICY = OzonRequestPolicy(retry_safe=False)
HANDOFF_TO_DRAFT_WAREHOUSE_TYPE = {
    "WAREHOUSE_TYPE_DELIVERY_POINT": "DELIVERY_POINT",
    "WAREHOUSE_TYPE_ORDERS_RECEIVING_POINT": "ORDERS_RECEIVING_POINT",
    "WAREHOUSE_TYPE_SORTING_CENTER": "SORTING_CENTER",
    "WAREHOUSE_TYPE_FULL_FILLMENT": "FULL_FILLMENT",
    "WAREHOUSE_TYPE_CROSS_DOCK": "CROSS_DOCK",
}


@dataclass(frozen=True, slots=True)
class DraftClusterIdentity:
    destination_cluster_id: str
    macrolocal_cluster_id: int


@dataclass(frozen=True, slots=True)
class DraftCreateRequest:
    path: str
    payload: dict
    supply_type: str


def _normalized_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def resolve_candidate_cluster_identities(candidate: CandidateShipment, source_clusters: tuple[Cluster, ...]) -> tuple[DraftClusterIdentity, ...]:
    result = []
    for destination in candidate.cluster_ids:
        numeric = [row for row in source_clusters if str(row.cluster_id) == destination]
        matches = numeric or [row for row in source_clusters if _normalized_name(row.name) == _normalized_name(destination)]
        if not matches:
            raise ValueError("MACROLOCAL_CLUSTER_UNRESOLVED")
        if len(matches) != 1:
            raise ValueError("MACROLOCAL_CLUSTER_AMBIGUOUS")
        cluster_id = matches[0].cluster_id
        if isinstance(cluster_id, bool) or not isinstance(cluster_id, int) or cluster_id <= 0:
            raise ValueError("MACROLOCAL_CLUSTER_UNRESOLVED")
        result.append(DraftClusterIdentity(destination, cluster_id))
    return tuple(result)


def _wire_sku(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, str) or not value or not value.isascii() or not value.isdecimal():
        raise ValueError("OZON_SKU_IDENTITY_INVALID")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("OZON_SKU_IDENTITY_INVALID")
    return parsed


def _items(candidate: CandidateShipment, destination: str) -> list[dict]:
    return [{"quantity": row.quantity, "sku": _wire_sku(row.sku)} for row in candidate.assignments if row.destination_cluster_id == destination]


def build_draft_create_request(candidate: CandidateShipment, cluster_identities: tuple[DraftClusterIdentity, ...]) -> DraftCreateRequest:
    if tuple(x.destination_cluster_id for x in cluster_identities) != candidate.cluster_ids:
        raise ValueError("MACROLOCAL_CLUSTER_IDENTITY_MISMATCH")
    clusters = [{"items": _items(candidate, identity.destination_cluster_id), "macrolocal_cluster_id": identity.macrolocal_cluster_id} for identity in cluster_identities]
    count = len(clusters)
    if candidate.method is ShipmentMethod.DIRECT:
        if count != 1:
            raise ValueError("DIRECT_REQUIRES_EXACTLY_ONE_CLUSTER")
        return DraftCreateRequest(DRAFT_DIRECT_CREATE, {"cluster_info": clusters[0], "deletion_sku_mode": "PARTIAL"}, "DIRECT")
    if count > 20:
        raise ValueError("MULTI_CLUSTER_LIMIT_EXCEEDED")
    if candidate.seller_warehouse_id is None or candidate.handoff_point_id is None:
        raise ValueError("CROSSDOCK_DELIVERY_INFO_REQUIRED")
    warehouse_type = HANDOFF_TO_DRAFT_WAREHOUSE_TYPE.get(candidate.handoff_warehouse_type or "")
    if warehouse_type is None:
        raise ValueError("HANDOFF_WAREHOUSE_TYPE_UNSUPPORTED")
    delivery = {"drop_off_warehouse": {"warehouse_id": candidate.handoff_point_id, "warehouse_type": warehouse_type},
                "seller_warehouse_id": candidate.seller_warehouse_id, "type": "DROPOFF"}
    payload = {"deletion_sku_mode": "PARTIAL", "delivery_info": delivery}
    if count == 1:
        payload["cluster_info"] = clusters[0]
        return DraftCreateRequest(DRAFT_CROSSDOCK_CREATE, payload, "CROSSDOCK")
    payload["clusters_info"] = clusters
    return DraftCreateRequest(DRAFT_MULTI_CLUSTER_CREATE, payload, "MULTI_CLUSTER")
