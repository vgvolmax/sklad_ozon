import pytest
from backend.ozon.adapters.inbound import SupplyState, _fetch_bundles, _fetch_details, _fetch_order_ids, classify_supply_state, fetch_inbound, normalize_inbound
from backend.ozon.endpoints import SUPPLY_ORDER_BUNDLE_PATH, SUPPLY_ORDER_GET_PATH, SUPPLY_ORDER_LIST_PATH

UUID="550e8400-e29b-41d4-a716-446655440000"

@pytest.mark.parametrize(("raw","expected"),[("IN_TRANSIT",SupplyState.INBOUND),("COMPLETED",SupplyState.FINAL),("NEW",SupplyState.UNKNOWN)])
def test_state_classifier(raw,expected): assert classify_supply_state(raw) is expected


def test_warehouse_mapping_uuid_and_fail_closed_states():
    details=[{"order_id":7,"supplies":[
        {"state":"IN_TRANSIT","storage_warehouse":{"warehouse_id":501},"bundle_id":UUID},
        {"state":"COMPLETED","storage_warehouse":{"warehouse_id":501},"bundle_id":"final"},
        {"state":"UNKNOWN","storage_warehouse":{"warehouse_id":501},"bundle_id":"unknown"},
        {"state":"IN_TRANSIT","storage_warehouse":{"warehouse_id":999},"bundle_id":"unmapped"}]}]
    rows, diagnostics=normalize_inbound(details,{UUID:[{"sku":"S","quantity":3}]},{10:"Москва"},{501:10})
    assert [(r.sku,r.cluster,r.inbound_quantity) for r in rows]==[("S","Москва",3)]
    assert {d.code for d in diagnostics}=={"UNKNOWN_SUPPLY_STATE","UNRESOLVED_SUPPLY_CLUSTER"}


class Client:
    def __init__(self): self.calls=[]
    def post_json(self,path,payload,**kwargs):
        self.calls.append((path,payload))
        if path==SUPPLY_ORDER_LIST_PATH:return {"order_ids":[7],"last_id":""}
        if path==SUPPLY_ORDER_GET_PATH:return {"orders":[{"order_id":7,"supplies":[{"state":"IN_TRANSIT","storage_warehouse":{"warehouse_id":501},"bundle_id":UUID}]}]}
        if path==SUPPLY_ORDER_BUNDLE_PATH:return {"items":[{"sku":"S","quantity":4}],"total_count":1,"has_next":False,"last_id":""}
        raise AssertionError(path)


def test_wire_requests_preserve_opaque_bundle_id():
    client=Client(); rows, diagnostics=fetch_inbound(client,{10:"Москва"},{501:10})
    assert rows[0].inbound_quantity==4 and not diagnostics
    assert client.calls[1][1]=={"order_ids":[7]}
    assert client.calls[2][1]=={"bundle_ids":[UUID],"limit":100}


def test_bundle_top_level_items_paginate_one_bundle_at_a_time():
    class Paged:
        def __init__(self): self.calls=[]
        def post_json(self,path,payload,**kwargs):
            self.calls.append(payload); return {"items":[{"sku":"S","quantity":len(self.calls)}],"has_next":len(self.calls)==1,"last_id":"next"}
    client=Paged(); result=_fetch_bundles(client,[UUID,"other"])
    assert result[UUID]==[{"sku":"S","quantity":1},{"sku":"S","quantity":2}]
    assert client.calls[1]=={"bundle_ids":[UUID],"limit":100,"last_id":"next"}
    assert client.calls[2]["bundle_ids"]==["other"]


def test_supply_list_last_id_paginates():
    class Paged:
        def __init__(self):self.calls=[]
        def post_json(self,path,payload,**kwargs):self.calls.append(payload);return {"order_ids":[len(self.calls)],"last_id":"next" if len(self.calls)==1 else ""}
    c=Paged(); assert _fetch_order_ids(c)==[1,2] and c.calls[1]["last_id"]=="next"


@pytest.mark.parametrize("returned", [
    [{"order_id": 7}],
    [{"order_id": 7}, {"order_id": 7}],
    [{"order_id": 7}, {"order_id": 9}],
])
def test_supply_details_must_exactly_match_requested_ids(returned):
    class DetailsClient:
        def post_json(self, _path, _payload, **_kwargs):
            return {"orders": returned}

    with pytest.raises(ValueError, match="detail|match|duplicate"):
        _fetch_details(DetailsClient(), [7, 8])
