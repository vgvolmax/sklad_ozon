from datetime import date
from decimal import Decimal

import pytest

from backend.ozon.endpoints import (DRAFT_CROSSDOCK_CREATE,DRAFT_DIRECT_CREATE,
                                    DRAFT_MULTI_CLUSTER_CREATE)
from backend.ozon.supply_drafts import CREATE_POLICY,build_draft_create_request
from backend.shipment.contracts import CandidateAssignment,CandidateShipment,ShipmentMethod


def candidate(method,clusters=("1",),*,seller=None,handoff=None,warehouse_type=None):
    rows=tuple(CandidateAssignment(f"SKU-{c}",f"A-{c}",c,2,1,Decimal("1"),Decimal("2"),"single",("A",)) for c in clusters)
    return CandidateShipment("candidate",method,seller,handoff,warehouse_type,clusters,rows,2*len(rows),Decimal(2*len(rows)),())


def test_method_specific_payloads_conserve_quantities_and_disable_retry():
    direct=build_draft_create_request(candidate(ShipmentMethod.DIRECT))
    assert direct.path==DRAFT_DIRECT_CREATE
    assert direct.payload=={"cluster_info":{"cluster_id":"1","items":[{"sku":"SKU-1","quantity":2}]}}
    assert CREATE_POLICY.retry_safe is False
    single=build_draft_create_request(candidate(ShipmentMethod.PVZ_CROSSDOCK,seller=4,handoff=5,warehouse_type="PVZ"))
    assert single.path==DRAFT_CROSSDOCK_CREATE
    assert single.payload["delivery_info"]=={"seller_warehouse_id":4,"drop_off_warehouse":{"warehouse_id":5,"warehouse_type":"PVZ"}}
    multi=build_draft_create_request(candidate(ShipmentMethod.SC_CROSSDOCK,("1","2"),seller=4,handoff=5,warehouse_type="SC"))
    assert multi.path==DRAFT_MULTI_CLUSTER_CREATE
    assert [x["items"][0]["quantity"] for x in multi.payload["clusters_info"]]==[2,2]


def test_invalid_method_cluster_counts_fail_before_a_client_exists():
    with pytest.raises(ValueError): build_draft_create_request(candidate(ShipmentMethod.DIRECT,("1","2")))
    with pytest.raises(ValueError): build_draft_create_request(candidate(ShipmentMethod.SC_CROSSDOCK,tuple(map(str,range(21))),seller=4,handoff=5,warehouse_type="SC"))


def test_active_runtime_does_not_contain_supply_create_endpoint():
    from pathlib import Path
    sources="".join(path.read_text() for path in Path("backend").rglob("*.py"))
    forbidden="/v2/draft/"+"supply/create"
    assert forbidden not in sources
    assert '"/v1/draft/create"' not in sources
