from decimal import Decimal
import pytest
from backend.ozon.endpoints import DRAFT_CROSSDOCK_CREATE,DRAFT_DIRECT_CREATE,DRAFT_MULTI_CLUSTER_CREATE
from backend.ozon.source_contracts import Cluster
from backend.ozon.supply_drafts import CREATE_POLICY,build_draft_create_request,resolve_candidate_cluster_identities
from backend.shipment.contracts import CandidateAssignment,CandidateShipment,ShipmentMethod

def candidate(method,clusters=("Москва",),*,seller=None,handoff=None,warehouse_type=None,skus=None):
    skus=skus or tuple(str(100+i) for i in range(len(clusters)))
    rows=tuple(CandidateAssignment(skus[i],f"A-{c}",c,2,1,Decimal("1"),Decimal("2"),"single",("A",)) for i,c in enumerate(clusters))
    return CandidateShipment("candidate",method,seller,handoff,warehouse_type,clusters,rows,2*len(rows),Decimal(2*len(rows)),())

def identities(c):return resolve_candidate_cluster_identities(c,(Cluster(111,"Москва"),Cluster(222,"Казань")))

def test_current_method_specific_payloads_and_anti_synthetic_guard():
    c=candidate(ShipmentMethod.DIRECT);direct=build_draft_create_request(c,identities(c))
    assert direct.path==DRAFT_DIRECT_CREATE
    assert direct.payload=={"cluster_info":{"items":[{"quantity":2,"sku":100}],"macrolocal_cluster_id":111},"deletion_sku_mode":"PARTIAL"}
    assert "cluster_id" not in direct.payload["cluster_info"] and CREATE_POLICY.retry_safe is False
    c=candidate(ShipmentMethod.PVZ_CROSSDOCK,seller=4,handoff=5,warehouse_type="WAREHOUSE_TYPE_DELIVERY_POINT")
    single=build_draft_create_request(c,identities(c))
    assert single.path==DRAFT_CROSSDOCK_CREATE
    assert single.payload["delivery_info"]=={"drop_off_warehouse":{"warehouse_id":5,"warehouse_type":"DELIVERY_POINT"},"seller_warehouse_id":4,"type":"DROPOFF"}
    c=candidate(ShipmentMethod.SC_CROSSDOCK,("Москва","Казань"),seller=4,handoff=5,warehouse_type="WAREHOUSE_TYPE_SORTING_CENTER")
    multi=build_draft_create_request(c,identities(c))
    assert multi.path==DRAFT_MULTI_CLUSTER_CREATE
    assert [x["macrolocal_cluster_id"] for x in multi.payload["clusters_info"]]==[111,222]
    assert [x["items"][0]["quantity"] for x in multi.payload["clusters_info"]]==[2,2]

def test_cluster_resolver_is_exact_and_fail_closed():
    clusters=(Cluster(111," Москва "),Cluster(222,"МОСКВА"))
    c=candidate(ShipmentMethod.DIRECT,("111",))
    assert identities(c)[0].macrolocal_cluster_id==111
    with pytest.raises(ValueError,match="AMBIGUOUS"):resolve_candidate_cluster_identities(candidate(ShipmentMethod.DIRECT),clusters)
    with pytest.raises(ValueError,match="UNRESOLVED"):resolve_candidate_cluster_identities(candidate(ShipmentMethod.DIRECT,("Моск",)),clusters)

def test_invalid_sku_and_handoff_type_fail_before_network():
    c=candidate(ShipmentMethod.DIRECT,skus=("123.0",))
    with pytest.raises(ValueError,match="OZON_SKU_IDENTITY_INVALID"):build_draft_create_request(c,identities(c))
    c=candidate(ShipmentMethod.PVZ_CROSSDOCK,seller=4,handoff=5,warehouse_type="DELIVERY_POINT")
    with pytest.raises(ValueError,match="HANDOFF_WAREHOUSE_TYPE_UNSUPPORTED"):build_draft_create_request(c,identities(c))

def test_invalid_method_cluster_counts():
    c=candidate(ShipmentMethod.DIRECT,("Москва","Казань"))
    with pytest.raises(ValueError):build_draft_create_request(c,identities(c))

def test_active_runtime_does_not_contain_forbidden_endpoints():
    from pathlib import Path
    sources="".join(path.read_text() for path in Path("backend").rglob("*.py"))
    assert "/v2/draft/"+"supply/create" not in sources
    assert '"/v1/draft/create"' not in sources and '"/v1/draft/create/info"' not in sources and '"/v1/draft/timeslot/info"' not in sources
