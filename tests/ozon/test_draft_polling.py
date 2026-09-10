from datetime import date,datetime,timezone
from backend.ozon.client import OzonClientError
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.draft_contracts import ValidationState
from backend.ozon.draft_validation import DraftValidationService,ozon_business_today
from backend.ozon.endpoints import DRAFT_CREATE_INFO,DRAFT_TIMESLOT_INFO
from backend.ozon.source_contracts import Cluster
from backend.shipment.contracts import ShipmentMethod,ShipmentScenario
from tests.ozon.test_supply_drafts import candidate
SCENARIO=ShipmentScenario(("Москва",),date(2026,9,11),date(2026,9,12),(ShipmentMethod.DIRECT,),1,1)
CLUSTERS=(Cluster(111,"Москва"),)
class FakeClient:
 def __init__(self,responses):self.responses=list(responses);self.calls=[]
 def post_json(self,path,payload,*,policy):
  self.calls.append((path,payload,policy));value=self.responses.pop(0)
  if isinstance(value,Exception):raise value
  return value
def service(client,clock=lambda:0):return DraftValidationService(client,clock=clock,today=lambda:date(2026,9,10),utcnow=lambda:datetime(2026,9,10,tzinfo=timezone.utc),sleeper=lambda _:None)
def warehouse(warehouse_id=9001,state="FULL_AVAILABLE",invalid_reason="UNSPECIFIED",rank=1,score=100):
 return {"availability_status":{"state":state,"invalid_reason":invalid_reason},"storage_warehouse":{"warehouse_id":warehouse_id},"total_rank":rank,"total_score":score}
def info(status="SUCCESS",errors=None,warehouses=None):
 rows=[warehouse()] if warehouses is None else warehouses
 return {"status":status,"clusters":[{"cluster_name":"Москва","macrolocal_cluster_id":111,"supply_type":"DIRECT","warehouses":rows}],"errors":errors or []}
def slots(rows=None,error="UNSPECIFIED"):
 return {"error_reason":error,"result":{"drop_off_warehouse_timeslots":{"current_time_in_timezone":"2026-09-10T12:00:00+03:00","days":([{"date_in_timezone":"2026-09-11","timeslots":rows}] if rows is not None else []),"warehouse_timezone":"Europe/Moscow"},"requested_date_from":"2026-09-11","requested_date_to":"2026-09-12"}}
def validate(svc,cands):return svc.validate(cands,SCENARIO,provenance="p",source_clusters=CLUSTERS)
def validate_cancelled(svc,cands,cancelled):return svc.validate(cands,SCENARIO,provenance="p",source_clusters=CLUSTERS,cancelled=cancelled)
def test_ambiguous_create_is_once_and_quarantined():
 client=FakeClient([OzonClientError(OzonErrorCode.UNAVAILABLE,"lost")]);svc=service(client)
 assert validate(svc,(candidate(ShipmentMethod.DIRECT),))[0].state is ValidationState.OUTCOME_UNKNOWN
 assert validate(svc,(candidate(ShipmentMethod.DIRECT),))[0].state is ValidationState.OUTCOME_UNKNOWN and len(client.calls)==1

def test_in_progress_success_current_timeslot_wire():
 rows=[{"from_in_timezone":"2026-09-11T12:00:00+03:00","to_in_timezone":"2026-09-11T13:00:00+03:00"},{"from_in_timezone":"2026-09-11T09:00:00+03:00","to_in_timezone":"2026-09-11T10:00:00+03:00"}]
 client=FakeClient([{"draft_id":7,"errors":[]},{"status":"IN_PROGRESS","clusters":[],"errors":[]},info(),slots(rows)])
 option=validate(service(client),(candidate(ShipmentMethod.DIRECT),))[0]
 assert option.state is ValidationState.ACCEPTED and [x.from_dt.hour for x in option.timeslots]==[9,12]
 payload=client.calls[-1][1];assert payload["selected_cluster_warehouses"]==[{"macrolocal_cluster_id":111,"storage_warehouse_id":9001}]
 assert "cluster_id" not in payload["selected_cluster_warehouses"][0] and "warehouse_id" not in payload["selected_cluster_warehouses"][0]

def test_cancel_after_create_preserves_draft_id_and_stops_calls():
 client=FakeClient([{"draft_id":1,"errors":[]}]);svc=service(client)
 option=validate_cancelled(svc,(candidate(ShipmentMethod.DIRECT),),lambda:len(client.calls)==1)[0]
 assert option.state is ValidationState.UNAVAILABLE
 assert option.reason_codes==("VALIDATION_CANCELLED",) and option.draft_id==1
 assert len(client.calls)==1

def test_cancel_after_in_progress_stops_before_sleep_and_next_poll():
 client=FakeClient([{"draft_id":2,"errors":[]},{"status":"IN_PROGRESS","clusters":[],"errors":[]}])
 slept=[];svc=DraftValidationService(client,clock=lambda:0,today=lambda:date(2026,9,10),utcnow=lambda:datetime(2026,9,10,tzinfo=timezone.utc),sleeper=slept.append)
 option=validate_cancelled(svc,(candidate(ShipmentMethod.DIRECT),),lambda:sum(call[0]==DRAFT_CREATE_INFO for call in client.calls)==1)[0]
 assert option.state is ValidationState.UNAVAILABLE
 assert option.reason_codes==("VALIDATION_CANCELLED",) and option.draft_id==2
 assert [call[0] for call in client.calls[1:]]==[DRAFT_CREATE_INFO] and slept==[]

def test_cancel_after_success_preserves_evidence_and_stops_before_timeslots():
 client=FakeClient([{"draft_id":3,"errors":[]},info()]);svc=service(client)
 option=validate_cancelled(svc,(candidate(ShipmentMethod.DIRECT),),lambda:any(call[0]==DRAFT_CREATE_INFO for call in client.calls))[0]
 assert option.state is ValidationState.UNAVAILABLE
 assert option.reason_codes==("VALIDATION_CANCELLED",) and option.draft_id==3
 assert option.accepted_assignments and option.warehouse_evidence
 assert [call[0] for call in client.calls[1:]]==[DRAFT_CREATE_INFO]

def test_rejected_resolution_partial_and_empty_slots_preserve_both_causes():
 errors=[{"items_validation":[{"macrolocal_cluster_id":111,"rejected_items":[{"sku":101,"reasons":["BAD"]}]}]}]
 c=candidate(ShipmentMethod.DIRECT,("Москва",),skus=("100",))
 # use two rows in same cluster to permit partial
 from decimal import Decimal
 from backend.shipment.contracts import CandidateAssignment,CandidateShipment
 rows=(c.assignments[0],CandidateAssignment("101","B","Москва",3,1,Decimal(1),Decimal(3),"single",("A",)))
 c=CandidateShipment("partial",ShipmentMethod.DIRECT,None,None,None,("Москва",),rows,5,Decimal(5),())
 client=FakeClient([{"draft_id":8,"errors":[]},info(errors=errors),slots(None)])
 option=validate(service(client),(c,))[0]
 assert option.state is ValidationState.PARTIAL and option.reason_codes==("OZON_PARTIAL_ACCEPTANCE","BAD","NO_TIMESLOT")
 assert option.rejected_assignments[0].quantity==3

def test_failed_and_unspecified_fail_closed():
 failed=FakeClient([{"draft_id":1,"errors":[]},info(status="FAILED",errors=[{"error_reasons":["INVALID_SELLER_WAREHOUSE"]}])])
 failed_option=validate(service(failed),(candidate(ShipmentMethod.DIRECT),))[0]
 assert failed_option.state is ValidationState.REJECTED
 assert failed_option.reason_codes==("OZON_REJECTED_CANDIDATE","INVALID_SELLER_WAREHOUSE")
 bad=FakeClient([{"draft_id":1,"errors":[]},info(status="UNSPECIFIED")])
 option=validate(service(bad),(candidate(ShipmentMethod.DIRECT),))[0]
 assert option.state is ValidationState.UNAVAILABLE and option.reason_codes==("OZON_INVALID_DRAFT_RESPONSE",)

def test_timeslot_api_error_is_not_no_timeslot():
 client=FakeClient([{"draft_id":1,"errors":[]},info(),slots([],"INVALID_CLUSTERS_COUNT")])
 option=validate(service(client),(candidate(ShipmentMethod.DIRECT),))[0]
 assert option.state is ValidationState.UNAVAILABLE and option.reason_codes==("OZON_TIMESLOT_REQUEST_REJECTED",)

def test_third_create_in_rolling_minute_is_locally_rate_limited():
 cs=tuple(candidate(ShipmentMethod.DIRECT) for _ in range(3))
 # distinct IDs avoid cache
 from dataclasses import replace
 cs=tuple(replace(c,candidate_id=str(i)) for i,c in enumerate(cs))
 client=FakeClient(sum(([{"draft_id":i+1,"errors":[]},info(),slots([])] for i in range(2)),[]))
 options=validate(service(client),cs)
 assert options[2].state is ValidationState.RATE_LIMITED and options[2].reason_codes==("DRAFT_RATE_BUDGET_EXHAUSTED",) and len(client.calls)==6

def test_partial_and_not_available_warehouses_fail_closed_without_timeslot_call():
 for state in ("PARTIAL_AVAILABLE","NOT_AVAILABLE","UNSPECIFIED","SOME_NEW_STATE"):
  client=FakeClient([{"draft_id":1,"errors":[]},info(warehouses=[warehouse(state=state)])])
  option=validate(service(client),(candidate(ShipmentMethod.DIRECT),))[0]
  assert option.state is ValidationState.UNAVAILABLE
  assert option.reason_codes==("OZON_STORAGE_WAREHOUSE_UNAVAILABLE",)
  assert option.warehouse_evidence[0].availability_state==state
  assert [call[0] for call in client.calls]==[client.calls[0][0],DRAFT_CREATE_INFO]

def test_available_warehouse_is_selected_and_preserved_for_timeslots():
 client=FakeClient([{"draft_id":1,"errors":[]},info(warehouses=[warehouse(9007,state="AVAILABLE")]),slots([])])
 option=validate(service(client),(candidate(ShipmentMethod.DIRECT),))[0]
 assert option.state is ValidationState.NO_TIMESLOT
 assert client.calls[-1][0]==DRAFT_TIMESLOT_INFO
 assert client.calls[-1][1]["selected_cluster_warehouses"]==[{"macrolocal_cluster_id":111,"storage_warehouse_id":9007}]

def test_full_available_warehouse_remains_eligible_for_timeslots():
 client=FakeClient([{"draft_id":1,"errors":[]},info(warehouses=[warehouse(9008,state="FULL_AVAILABLE")]),slots([])])
 validate(service(client),(candidate(ShipmentMethod.DIRECT),))
 assert client.calls[-1][0]==DRAFT_TIMESLOT_INFO
 assert client.calls[-1][1]["selected_cluster_warehouses"][0]["storage_warehouse_id"]==9008

def test_first_full_available_warehouse_is_selected_in_response_order():
 warehouses=[warehouse(9001,"NOT_AVAILABLE",score=1000),warehouse(9002,score=1),warehouse(9003,score=999)]
 client=FakeClient([{"draft_id":1,"errors":[]},info(warehouses=warehouses),slots([])])
 validate(service(client),(candidate(ShipmentMethod.DIRECT),))
 assert client.calls[-1][0]==DRAFT_TIMESLOT_INFO
 assert client.calls[-1][1]["selected_cluster_warehouses"]==[{"macrolocal_cluster_id":111,"storage_warehouse_id":9002}]

def test_full_eligible_warehouse_with_blocking_invalid_reason_is_invalid_response():
 for state in ("AVAILABLE","FULL_AVAILABLE"):
  client=FakeClient([{"draft_id":1,"errors":[]},info(warehouses=[warehouse(state=state,invalid_reason="BLOCKED")])])
  option=validate(service(client),(candidate(ShipmentMethod.DIRECT),))[0]
  assert option.state is ValidationState.UNAVAILABLE
  assert option.reason_codes==("OZON_INVALID_DRAFT_RESPONSE",)
  assert len(client.calls)==2

def test_global_reasons_are_deduplicated_and_unspecified_or_blank_are_ignored():
 errors=[{"error_reasons":["","UNSPECIFIED","SOME_REASON","SOME_REASON"]},{"error_reasons":["NEXT_REASON","SOME_REASON"]}]
 client=FakeClient([{"errors":errors}])
 option=validate(service(client),(candidate(ShipmentMethod.DIRECT),))[0]
 assert option.state is ValidationState.REJECTED
 assert option.reason_codes==("OZON_REJECTED_CANDIDATE","SOME_REASON","NEXT_REASON")

def test_create_errors_with_valid_draft_id_are_preserved_and_info_is_authoritative():
 create_errors=[{"error_reasons":["PRELIMINARY_REASON"],"error_message":"detail","message":"evidence","macrolocal_cluster_ids":[111],"skus":[100]}]
 client=FakeClient([{"draft_id":7,"errors":create_errors},info(status="FAILED",errors=[{"error_reasons":["FINAL_REASON"]}])])
 option=validate(service(client),(candidate(ShipmentMethod.DIRECT),))[0]
 assert [call[0] for call in client.calls[1:]]==[DRAFT_CREATE_INFO]
 assert option.reason_codes==("OZON_REJECTED_CANDIDATE","PRELIMINARY_REASON","FINAL_REASON")

def test_accepted_preserves_deduplicated_create_and_info_reasons():
 create_errors=[{"error_reasons":["SAME_REASON","PRELIMINARY_REASON"]}]
 final_errors=[{"error_reasons":["SAME_REASON","FINAL_REASON"]}]
 timeslots=[{"from_in_timezone":"2026-09-11T09:00:00+03:00","to_in_timezone":"2026-09-11T10:00:00+03:00"}]
 client=FakeClient([{"draft_id":7,"errors":create_errors},info(errors=final_errors),slots(timeslots)])
 option=validate(service(client),(candidate(ShipmentMethod.DIRECT),))[0]
 assert option.state is ValidationState.ACCEPTED
 assert option.reason_codes==("SAME_REASON","PRELIMINARY_REASON","FINAL_REASON")

def test_no_timeslot_preserves_create_and_info_reasons_before_state_reason():
 create_errors=[{"error_reasons":["PRELIMINARY_REASON"]}]
 final_errors=[{"error_reasons":["FINAL_REASON","NO_TIMESLOT"]}]
 client=FakeClient([{"draft_id":7,"errors":create_errors},info(errors=final_errors),slots(None)])
 option=validate(service(client),(candidate(ShipmentMethod.DIRECT),))[0]
 assert option.state is ValidationState.NO_TIMESLOT
 assert option.reason_codes==("PRELIMINARY_REASON","FINAL_REASON","NO_TIMESLOT")

def test_partial_preserves_global_and_item_reasons_before_no_timeslot():
 errors=[{"error_reasons":["GLOBAL_REASON"],"items_validation":[{"macrolocal_cluster_id":111,"rejected_items":[{"sku":101,"reasons":["ITEM_REASON","ITEM_REASON_2"]}]}]}]
 from decimal import Decimal
 from backend.shipment.contracts import CandidateAssignment,CandidateShipment
 c=candidate(ShipmentMethod.DIRECT,("Москва",),skus=("100",))
 rows=(c.assignments[0],CandidateAssignment("101","B","Москва",3,1,Decimal(1),Decimal(3),"single",("A",)))
 c=CandidateShipment("partial-global",ShipmentMethod.DIRECT,None,None,None,("Москва",),rows,5,Decimal(5),())
 client=FakeClient([{"draft_id":8,"errors":[]},info(errors=errors),slots(None)])
 option=validate(service(client),(c,))[0]
 assert option.reason_codes==("OZON_PARTIAL_ACCEPTANCE","GLOBAL_REASON","ITEM_REASON","ITEM_REASON_2","NO_TIMESLOT")
 assert option.rejected_assignments[0].code=="ITEM_REASON"

def test_multiple_rejected_skus_preserve_all_deduplicated_reasons_in_wire_order():
 errors=[{"items_validation":[{"macrolocal_cluster_id":111,"rejected_items":[
  {"sku":101,"reasons":["REASON_A","REASON_SHARED"]},
  {"sku":102,"reasons":["REASON_B","REASON_SHARED"]},
 ]}]}]
 from decimal import Decimal
 from backend.shipment.contracts import CandidateAssignment,CandidateShipment
 rows=(
  CandidateAssignment("100","A","Москва",2,1,Decimal(1),Decimal(2),"single",("A",)),
  CandidateAssignment("101","B","Москва",3,1,Decimal(1),Decimal(3),"single",("A",)),
  CandidateAssignment("102","C","Москва",4,1,Decimal(1),Decimal(4),"single",("A",)),
 )
 c=CandidateShipment("multi-rejected",ShipmentMethod.DIRECT,None,None,None,("Москва",),rows,9,Decimal(9),())
 client=FakeClient([{"draft_id":8,"errors":[]},info(errors=errors),slots([])])
 option=validate(service(client),(c,))[0]
 assert option.reason_codes==("OZON_PARTIAL_ACCEPTANCE","REASON_A","REASON_SHARED","REASON_B","NO_TIMESLOT")
 assert [row.code for row in option.rejected_assignments]==["REASON_A","REASON_B"]

def test_ozon_business_today_uses_utc_plus_three_at_utc_day_boundary():
 assert ozon_business_today(lambda:datetime(2026,9,10,21,30,tzinfo=timezone.utc))==date(2026,9,11)

def test_default_date_provider_drives_28_day_range_from_ozon_business_date(monkeypatch):
 monkeypatch.setattr("backend.ozon.draft_validation.ozon_business_today",lambda:date(2026,9,11))
 scenario=ShipmentScenario(("Москва",),date(2026,9,11),date(2026,10,9),(ShipmentMethod.DIRECT,),1,1)
 client=FakeClient([{"draft_id":1,"errors":[]},info(),slots([])])
 option=DraftValidationService(client,clock=lambda:0,utcnow=lambda:datetime(2026,9,10,21,30,tzinfo=timezone.utc),sleeper=lambda _:None).validate((candidate(ShipmentMethod.DIRECT),),scenario,provenance="p",source_clusters=CLUSTERS)[0]
 assert option.state is ValidationState.NO_TIMESLOT
