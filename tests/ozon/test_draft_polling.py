from datetime import date,datetime,timezone

from backend.ozon.client import OzonClientError
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.draft_contracts import ValidationState
from backend.ozon.draft_validation import DraftValidationService
from backend.ozon.endpoints import DRAFT_CREATE_INFO,DRAFT_TIMESLOT_INFO
from backend.shipment.contracts import ShipmentMethod,ShipmentScenario
from tests.ozon.test_supply_drafts import candidate


SCENARIO=ShipmentScenario(("1",),date(2026,9,11),date(2026,9,12),(ShipmentMethod.DIRECT,),1,1)


class FakeClient:
    def __init__(self,responses): self.responses=list(responses); self.calls=[]
    def post_json(self,path,payload,*,policy):
        self.calls.append((path,payload,policy))
        value=self.responses.pop(0)
        if isinstance(value,Exception): raise value
        return value


def service(client,clock=lambda:0):
    return DraftValidationService(client,clock=clock,today=lambda:date(2026,9,10),
        utcnow=lambda:datetime(2026,9,10,tzinfo=timezone.utc),sleeper=lambda _:None)


def accepted_info(rejected=()):
    items=[] if rejected else [{"sku":"SKU-1","cluster_id":"1","quantity":2}]
    return {"result":{"status":"completed","accepted_items":items,"rejected_items":list(rejected),
        "warehouses":[{"cluster_id":"1","warehouse_id":99}],"travel_time_days":1}}


def test_ambiguous_create_is_once_and_outcome_unknown():
    client=FakeClient([OzonClientError(OzonErrorCode.UNAVAILABLE,"lost")])
    option=service(client).validate((candidate(ShipmentMethod.DIRECT),),SCENARIO,provenance="p")[0]
    assert option.state is ValidationState.OUTCOME_UNKNOWN
    assert option.reason_codes==("DRAFT_CREATE_OUTCOME_UNKNOWN",)
    assert len(client.calls)==1 and client.calls[0][2].retry_safe is False


def test_acceptance_fetches_ordered_deduplicated_live_timeslots():
    slots=[{"from":"2026-09-11T12:00:00+03:00","to":"2026-09-11T13:00:00+03:00"},
           {"from":"2026-09-11T09:00:00+03:00","to":"2026-09-11T10:00:00+03:00"}]
    client=FakeClient([{"result":{"draft_id":7}},accepted_info(),{"result":{"timeslots":slots}}])
    option=service(client).validate((candidate(ShipmentMethod.DIRECT),),SCENARIO,provenance="p")[0]
    assert option.state is ValidationState.ACCEPTED and option.draft_id==7
    assert [x.from_dt.hour for x in option.timeslots]==[9,12]
    assert client.calls[-1][0]==DRAFT_TIMESLOT_INFO
    assert client.calls[-1][1]["selected_cluster_warehouses"]==[{"cluster_id":"1","warehouse_id":99}]


def test_rejection_partial_no_slot_rate_limit_and_cache_are_causal():
    rejected={"sku":"SKU-1","cluster_id":"1","quantity":2,"code":"BAD","message":"no"}
    reject_client=FakeClient([{"result":{"rejected_items":[rejected]}}])
    assert service(reject_client).validate((candidate(ShipmentMethod.DIRECT),),SCENARIO,provenance="p")[0].state is ValidationState.REJECTED
    no_slots=FakeClient([{"draft_id":8},accepted_info(),{"timeslots":[]}])
    svc=service(no_slots)
    first=svc.validate((candidate(ShipmentMethod.DIRECT),),SCENARIO,provenance="p")[0]
    second=svc.validate((candidate(ShipmentMethod.DIRECT),),SCENARIO,provenance="p")[0]
    assert first.state is ValidationState.NO_TIMESLOT and second==first and len(no_slots.calls)==3
    limited=FakeClient([OzonClientError(OzonErrorCode.RATE_LIMITED,"slow",status=429)])
    assert service(limited).validate((candidate(ShipmentMethod.DIRECT),),SCENARIO,provenance="p")[0].state is ValidationState.RATE_LIMITED
