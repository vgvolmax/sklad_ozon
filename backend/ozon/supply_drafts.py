"""Lossless CandidateShipment to method-specific temporary-draft requests."""

from dataclasses import dataclass

from backend.shipment.contracts import CandidateShipment, ShipmentMethod
from .client import OzonRequestPolicy
from .endpoints import (DRAFT_CROSSDOCK_CREATE, DRAFT_DIRECT_CREATE,
                        DRAFT_MULTI_CLUSTER_CREATE)

CREATE_POLICY = OzonRequestPolicy(retry_safe=False)


@dataclass(frozen=True, slots=True)
class DraftCreateRequest:
    path: str
    payload: dict
    supply_type: str


def _items(candidate: CandidateShipment, cluster_id: str) -> list[dict]:
    return [{"sku": row.sku, "quantity": row.quantity} for row in candidate.assignments
            if row.destination_cluster_id == cluster_id]


def build_draft_create_request(candidate: CandidateShipment) -> DraftCreateRequest:
    if not isinstance(candidate, CandidateShipment):
        raise TypeError("candidate must be CandidateShipment")
    count = len(candidate.cluster_ids)
    if candidate.method is ShipmentMethod.DIRECT:
        if count != 1: raise ValueError("DIRECT_REQUIRES_EXACTLY_ONE_CLUSTER")
        cluster = candidate.cluster_ids[0]
        return DraftCreateRequest(DRAFT_DIRECT_CREATE,
            {"cluster_info": {"cluster_id": cluster, "items": _items(candidate, cluster)}}, "DIRECT")
    if count > 20: raise ValueError("MULTI_CLUSTER_LIMIT_EXCEEDED")
    if candidate.seller_warehouse_id is None or candidate.handoff_point_id is None or not candidate.handoff_warehouse_type:
        raise ValueError("CROSSDOCK_DELIVERY_INFO_REQUIRED")
    delivery = {"seller_warehouse_id": candidate.seller_warehouse_id,
                "drop_off_warehouse": {"warehouse_id": candidate.handoff_point_id,
                                       "warehouse_type": candidate.handoff_warehouse_type}}
    clusters = [{"cluster_id": cluster, "items": _items(candidate, cluster)}
                for cluster in candidate.cluster_ids]
    if count == 1:
        return DraftCreateRequest(DRAFT_CROSSDOCK_CREATE,
            {"cluster_info": clusters[0], "delivery_info": delivery}, "CROSSDOCK")
    return DraftCreateRequest(DRAFT_MULTI_CLUSTER_CREATE,
        {"clusters_info": clusters, "delivery_info": delivery}, "MULTI_CLUSTER")
