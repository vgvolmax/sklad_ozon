from datetime import date,datetime,timezone
from backend.ozon.client import OzonClientError
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.draft_contracts import ValidationState
from backend.ozon.draft_validation import DraftValidationService
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
def info(status="SUCCESS",errors=None,warehouses=True):
 return {"status":status,"clusters":[{"cluster_name":"Москва","macrolocal_cluster_id":111,"supply_type":"DIRECT","warehouses":([{"availability_status":{"state":"AVAILABLE","invalid_reason":"UNSPECIFIED"},"storage_warehouse":{"warehouse_id":9001},"total_rank":1,"total_score":100}] if warehouses else [])}],"errors":errors or []}
def slots(rows=None,error="UNSPECIFIED"):
 return {"error_reason":error,"result":{"drop_off_warehouse_timeslots":{"current_time_in_timezone":"2026-09-10T12:00:00+03:00","days":([{"date_in_timezone":"2026-09-11","timeslots":rows}] if rows is not None else []),"warehouse_timezone":"Europe/Moscow"},"requested_date_from":"2026-09-11","requested_date_to":"2026-09-12"}}
def validate(svc,cands):return svc.validate(cands,SCENARIO,provenance="p",source_clusters=CLUSTERS)
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
 assert option.state is ValidationState.PARTIAL and option.reason_codes==("OZON_PARTIAL_ACCEPTANCE","NO_TIMESLOT")
 assert option.rejected_assignments[0].quantity==3

def test_failed_and_unspecified_fail_closed():
 failed=FakeClient([{"draft_id":1,"errors":[]},info(status="FAILED")])
 assert validate(service(failed),(candidate(ShipmentMethod.DIRECT),))[0].state is ValidationState.REJECTED
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
