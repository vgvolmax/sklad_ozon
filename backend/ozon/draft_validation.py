"""Bounded current-wire orchestration for temporary draft validation."""
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
import hashlib, json, time
from threading import Event, RLock
from typing import Callable

from backend.shipment.contracts import CandidateAssignment, CandidateShipment, ShipmentScenario
from .client import OzonClientError, OzonRequestPolicy
from .contracts import OzonErrorCode
from .draft_contracts import OzonRejectedAssignment, OzonTimeslot, OzonWarehouseEvidence, ValidatedShipmentOption, ValidationState
from .endpoints import DRAFT_CREATE_INFO, DRAFT_TIMESLOT_INFO
from .source_contracts import Cluster, source_business_date
from .supply_drafts import CREATE_POLICY, DraftClusterIdentity, build_draft_create_request, resolve_candidate_cluster_identities

DEFAULT_MAX_NEW_DRAFTS=6
MAX_INFO_POLL_ATTEMPTS=5
POLL_INTERVAL_SECONDS=.25
MAX_POLL_DURATION_SECONDS=5.0
VALIDATION_CACHE_TTL_SECONDS=120.0
OUTCOME_UNKNOWN_TTL_SECONDS=24*60*60
VALIDATION_CACHE_MAX_ENTRIES=64
READ_POLICY=OzonRequestPolicy(retry_safe=True,max_attempts=3)
FULL_ELIGIBLE_WAREHOUSE_STATES=frozenset({"AVAILABLE","FULL_AVAILABLE"})

class InvalidDraftResponse(ValueError): pass
class TimeslotResponseError(ValueError): pass

@dataclass(frozen=True,slots=True)
class OzonDraftErrorEvidence:
    error_reasons: tuple[str,...]
    error_message: str
    message: str
    macrolocal_cluster_ids: tuple[int | str,...]
    skus: tuple[int | str,...]

@dataclass(frozen=True,slots=True)
class _DraftInfo:
    status: str
    accepted: tuple[CandidateAssignment,...]
    rejected: tuple[OzonRejectedAssignment,...]
    warehouses: tuple[OzonWarehouseEvidence,...]
    errors: tuple[OzonDraftErrorEvidence,...]
    rejected_reason_codes: tuple[str,...]

@dataclass(slots=True)
class _InFlightValidation:
    done: Event
    option: ValidatedShipmentOption | None = None
    error: BaseException | None = None


def _positive_int(value):
    return isinstance(value,int) and not isinstance(value,bool) and value>0

def _draft_id(response):
    if not isinstance(response,dict): raise InvalidDraftResponse("response")
    value=response.get("draft_id")
    if value is None:return None
    if not _positive_int(value):raise InvalidDraftResponse("draft_id")
    return value

def _wire_sku(value):
    if isinstance(value,bool):raise InvalidDraftResponse("sku")
    if isinstance(value,int) and value>0:return value
    raise InvalidDraftResponse("sku")

def _normalized_reason_codes(values):
    output=[]
    for value in values:
        if not isinstance(value,str):raise InvalidDraftResponse("error_reason")
        if value and value!="UNSPECIFIED" and value not in output:output.append(value)
    return tuple(output)

def ozon_business_today(utcnow=lambda:datetime.now(timezone.utc)):
    return source_business_date(utcnow())

def _normalize_errors(errors,candidate,identities):
    if not isinstance(errors,list):raise InvalidDraftResponse("errors")
    destination_by_macro={x.macrolocal_cluster_id:x.destination_cluster_id for x in identities}
    rejected_output=[];rejected_reason_codes=[];error_output=[]
    for error in errors:
        if not isinstance(error,dict):raise InvalidDraftResponse("error")
        reasons=error.get("error_reasons",[])
        macro_ids=error.get("macrolocal_cluster_ids",[])
        skus=error.get("skus",[])
        error_message=error.get("error_message","")
        message=error.get("message","")
        if not isinstance(reasons,list) or not isinstance(macro_ids,list) or not isinstance(skus,list) or not isinstance(error_message,str) or not isinstance(message,str):raise InvalidDraftResponse("error evidence")
        error_output.append(OzonDraftErrorEvidence(_normalized_reason_codes(reasons),error_message,message,tuple(macro_ids),tuple(skus)))
        for validation in error.get("items_validation",[]):
            if not isinstance(validation,dict):raise InvalidDraftResponse("items_validation")
            macro=validation.get("macrolocal_cluster_id")
            destination=destination_by_macro.get(macro)
            if destination is None:raise InvalidDraftResponse("rejected cluster")
            rejected=validation.get("rejected_items",[])
            if not isinstance(rejected,list):raise InvalidDraftResponse("rejected_items")
            for raw in rejected:
                if not isinstance(raw,dict):raise InvalidDraftResponse("rejected_item")
                sku=_wire_sku(raw.get("sku"))
                matches=[row for row in candidate.assignments if row.destination_cluster_id==destination and int(row.sku)==sku]
                if len(matches)!=1:raise InvalidDraftResponse("rejected identity")
                reasons=raw.get("reasons",[])
                if not isinstance(reasons,list):raise InvalidDraftResponse("reasons")
                normalized_reasons=_normalized_reason_codes(reasons)
                for reason in normalized_reasons:
                    if reason not in rejected_reason_codes:rejected_reason_codes.append(reason)
                code=normalized_reasons[0] if normalized_reasons else "OZON_REJECTED"
                rejected_output.append(OzonRejectedAssignment(matches[0].sku,matches[0].article,destination,matches[0].quantity,code,code))
    identities_seen=[(x.sku,x.destination_cluster_id) for x in rejected_output]
    if len(identities_seen)!=len(set(identities_seen)):raise InvalidDraftResponse("duplicate rejection")
    return tuple(rejected_output),tuple(error_output),tuple(rejected_reason_codes)

def _error_reason_codes(errors):
    return _normalized_reason_codes(reason for error in errors for reason in error.error_reasons)

def normalize_draft_info(response,candidate,identities):
    if not isinstance(response,dict):raise InvalidDraftResponse("response")
    status=response.get("status")
    if status=="IN_PROGRESS":return None
    if status not in {"SUCCESS","FAILED"}:raise InvalidDraftResponse("status")
    rejected,errors,rejected_reason_codes=_normalize_errors(response.get("errors",[]),candidate,identities)
    destination_by_macro={x.macrolocal_cluster_id:x.destination_cluster_id for x in identities}
    warehouses=[]
    clusters=response.get("clusters",[])
    if not isinstance(clusters,list):raise InvalidDraftResponse("clusters")
    seen_clusters=set()
    for cluster in clusters:
        if not isinstance(cluster,dict):raise InvalidDraftResponse("cluster")
        macro=cluster.get("macrolocal_cluster_id")
        if not _positive_int(macro) or macro not in destination_by_macro:raise InvalidDraftResponse("cluster identity")
        seen_clusters.add(macro)
        rows=cluster.get("warehouses",[])
        if not isinstance(rows,list):raise InvalidDraftResponse("warehouses")
        for raw in rows:
            if not isinstance(raw,dict):raise InvalidDraftResponse("warehouse")
            storage=raw.get("storage_warehouse")
            availability=raw.get("availability_status")
            if not isinstance(storage,dict) or not isinstance(availability,dict):raise InvalidDraftResponse("warehouse evidence")
            wid=storage.get("warehouse_id")
            state=availability.get("state")
            reason=availability.get("invalid_reason","")
            if not _positive_int(wid) or not isinstance(state,str) or not isinstance(reason,str):raise InvalidDraftResponse("warehouse evidence")
            warehouses.append(OzonWarehouseEvidence(destination_by_macro[macro],macro,wid,state,reason,raw.get("total_rank"),raw.get("total_score")))
    if status=="FAILED":return _DraftInfo(status,(),rejected,tuple(warehouses),errors,rejected_reason_codes)
    rejected_keys={(x.sku,x.destination_cluster_id) for x in rejected}
    accepted=tuple(x for x in candidate.assignments if (x.sku,x.destination_cluster_id) not in rejected_keys)
    if sum(x.quantity for x in accepted)+sum(x.quantity for x in rejected)!=candidate.total_qty:raise InvalidDraftResponse("quantity conservation")
    return _DraftInfo(status,accepted,rejected,tuple(warehouses),errors,rejected_reason_codes)

def _selected_warehouses(warehouses,identities):
    selected=[]
    for identity in identities:
        cluster_rows=[x for x in warehouses if x.macrolocal_cluster_id==identity.macrolocal_cluster_id]
        if any(x.availability_state in FULL_ELIGIBLE_WAREHOUSE_STATES and x.invalid_reason not in {"","UNSPECIFIED"} for x in cluster_rows):
            raise InvalidDraftResponse("warehouse availability contradiction")
        rows=[x for x in cluster_rows if x.availability_state in FULL_ELIGIBLE_WAREHOUSE_STATES and x.invalid_reason in {"","UNSPECIFIED"}]
        if not rows:raise ValueError("OZON_STORAGE_WAREHOUSE_UNAVAILABLE")
        # Preserve response order; rank is evidence, not a new optimizer.
        row=rows[0]
        selected.append({"macrolocal_cluster_id":identity.macrolocal_cluster_id,"storage_warehouse_id":row.storage_warehouse_id})
    return selected

def normalize_timeslots(response):
    if not isinstance(response,dict):raise InvalidDraftResponse("timeslot response")
    reason=response.get("error_reason")
    if reason=="REQUESTED_PERIOD_MORE_THAN_MAX":raise TimeslotResponseError("TIMESLOT_DATE_RANGE_UNSUPPORTED")
    if reason in {"INVALID_CLUSTERS_COUNT","INVALID_REQUESTED_CLUSTER_IDS"}:raise TimeslotResponseError("OZON_TIMESLOT_REQUEST_REJECTED")
    if reason!="UNSPECIFIED":raise InvalidDraftResponse("timeslot error_reason")
    result=response.get("result")
    if not isinstance(result,dict):raise InvalidDraftResponse("timeslot result")
    evidence=result.get("drop_off_warehouse_timeslots")
    if not isinstance(evidence,dict):raise InvalidDraftResponse("timeslot evidence")
    days=evidence.get("days")
    if not isinstance(days,list):raise InvalidDraftResponse("timeslot days")
    output=set()
    for day in days:
        if not isinstance(day,dict) or not isinstance(day.get("timeslots"),list):raise InvalidDraftResponse("timeslot day")
        for raw in day["timeslots"]:
            if not isinstance(raw,dict):raise InvalidDraftResponse("timeslot")
            try: slot=OzonTimeslot(datetime.fromisoformat(raw["from_in_timezone"]),datetime.fromisoformat(raw["to_in_timezone"]))
            except (KeyError,TypeError,ValueError) as exc:raise InvalidDraftResponse("timeslot") from exc
            output.add(slot)
    return tuple(sorted(output,key=lambda x:(x.from_dt,x.to_dt)))

class DraftValidationService:
    def __init__(self,client,*,clock:Callable[[],float]=time.monotonic,utcnow=lambda:datetime.now(timezone.utc),today=None,sleeper=time.sleep,cache_ttl=VALIDATION_CACHE_TTL_SECONDS,cache_size=VALIDATION_CACHE_MAX_ENTRIES):
        self.client=client;self.clock=clock;self.utcnow=utcnow;self.today=today or ozon_business_today;self.sleeper=sleeper;self.cache_ttl=cache_ttl;self.cache_size=cache_size
        self._cache=OrderedDict();self._create_attempts=deque();self._state_lock=RLock();self._inflight={}
    def _key(self,c,s,p):
        return hashlib.sha256(json.dumps([c.candidate_id,p,s.date_from.isoformat(),s.date_to.isoformat(),[(x.sku,x.destination_cluster_id,x.quantity) for x in c.assignments]],separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    def _option(self,c,state,reasons,**kw):
        return ValidatedShipmentOption(c.candidate_id,kw.get("draft_id"),state,c.method,c.seller_warehouse_id,c.handoff_point_id,tuple(kw.get("accepted",())),tuple(kw.get("rejected",())),tuple(kw.get("warehouses",())),None,tuple(kw.get("timeslots",())),self.utcnow().isoformat(),tuple(reasons))
    def _cached_option_locked(self,key,now):
        cached=self._cache.get(key)
        ttl=OUTCOME_UNKNOWN_TTL_SECONDS if cached and cached[1].state is ValidationState.OUTCOME_UNKNOWN else self.cache_ttl
        if cached and now-cached[0]<ttl:return cached[1]
        if cached:self._cache.pop(key,None)
        return None
    def _reserve_create_slot_locked(self,now):
        while self._create_attempts and now-self._create_attempts[0]>=86400:self._create_attempts.popleft()
        if sum(now-x<60 for x in self._create_attempts)>=2 or sum(now-x<3600 for x in self._create_attempts)>=50 or len(self._create_attempts)>=500:return False
        self._create_attempts.append(now)
        return True
    def _wait_for_flight(self,candidate,flight,cancelled):
        while not flight.done.wait(timeout=.05):
            if cancelled():return self._option(candidate,ValidationState.UNAVAILABLE,("VALIDATION_CANCELLED",))
        if flight.error is not None:raise flight.error
        if flight.option is None:raise RuntimeError("in-flight validation completed without a result")
        return flight.option
    def _publish_flight(self,key,flight,option=None,error=None):
        with self._state_lock:
            if error is None:
                self._cache[key]=(self.clock(),option)
                while len(self._cache)>self.cache_size:self._cache.popitem(last=False)
                flight.option=option
            else:flight.error=error
            self._inflight.pop(key,None)
            flight.done.set()
    def validate(self,candidates,scenario,*,provenance,source_clusters:tuple[Cluster,...],client=None,cancelled=lambda:False):
        active_client=client or self.client
        output=[];created=0
        for candidate in candidates:
            key=self._key(candidate,scenario,provenance)
            with self._state_lock:
                cached=self._cached_option_locked(key,self.clock());flight=self._inflight.get(key)
            if cancelled() and flight is None:break
            if cached is not None:output.append(cached);continue
            if flight is not None:
                output.append(self._wait_for_flight(candidate,flight,cancelled));continue
            if scenario.date_from<self.today() or scenario.date_to>self.today()+timedelta(days=28):
                output.append(self._option(candidate,ValidationState.UNAVAILABLE,("TIMESLOT_DATE_RANGE_UNSUPPORTED",)));continue
            try:identities=resolve_candidate_cluster_identities(candidate,source_clusters);create=build_draft_create_request(candidate,identities)
            except (ValueError,TypeError) as exc:
                output.append(self._option(candidate,ValidationState.UNAVAILABLE,(str(exc),)));continue
            with self._state_lock:
                cached=self._cached_option_locked(key,self.clock());flight=self._inflight.get(key)
                if cached is None and flight is None:
                    if created>=DEFAULT_MAX_NEW_DRAFTS or not self._reserve_create_slot_locked(self.clock()):
                        output.append(self._option(candidate,ValidationState.RATE_LIMITED,("DRAFT_RATE_BUDGET_EXHAUSTED",)));continue
                    flight=_InFlightValidation(Event());self._inflight[key]=flight;owner=True;created+=1
                else:owner=False
            if cached is not None:output.append(cached);continue
            if not owner:
                output.append(self._wait_for_flight(candidate,flight,cancelled));continue
            try:option=self._validate_one(candidate,scenario,identities,create,cancelled,active_client)
            except BaseException as exc:
                self._publish_flight(key,flight,error=exc);raise
            else:
                self._publish_flight(key,flight,option=option);output.append(option)
        return tuple(output)
    def _validate_one(self,candidate,scenario,identities,create,cancelled,client):
        preliminary_errors=();preliminary_rejected_reasons=()
        try:
            response=client.post_json(create.path,create.payload,policy=CREATE_POLICY);draft_id=_draft_id(response)
            errors=response.get("errors",[]) if isinstance(response,dict) else []
            rejected,preliminary_errors,preliminary_rejected_reasons=_normalize_errors(errors,candidate,identities)
            if draft_id is None:
                reasons=_normalized_reason_codes((*_error_reason_codes(preliminary_errors),*preliminary_rejected_reasons))
                if rejected or reasons:return self._option(candidate,ValidationState.REJECTED,("OZON_REJECTED_CANDIDATE",)+reasons,rejected=rejected)
                raise InvalidDraftResponse("missing draft_id")
        except OzonClientError as exc:
            if exc.code is OzonErrorCode.RATE_LIMITED:return self._option(candidate,ValidationState.RATE_LIMITED,("OZON_RATE_LIMITED",))
            if exc.code is OzonErrorCode.UNAVAILABLE and exc.status is None:return self._option(candidate,ValidationState.OUTCOME_UNKNOWN,("DRAFT_CREATE_OUTCOME_UNKNOWN",))
            return self._option(candidate,ValidationState.UNAVAILABLE,("OZON_INVALID_DRAFT_RESPONSE" if exc.code is OzonErrorCode.INVALID_RESPONSE else "OZON_UNAVAILABLE",))
        except (InvalidDraftResponse,ValueError,TypeError):return self._option(candidate,ValidationState.UNAVAILABLE,("OZON_INVALID_DRAFT_RESPONSE",))
        if cancelled():return self._option(candidate,ValidationState.UNAVAILABLE,("VALIDATION_CANCELLED",),draft_id=draft_id)
        info=None;deadline=self.clock()+MAX_POLL_DURATION_SECONDS
        for attempt in range(MAX_INFO_POLL_ATTEMPTS):
            if cancelled():return self._option(candidate,ValidationState.UNAVAILABLE,("VALIDATION_CANCELLED",),draft_id=draft_id)
            try:info=normalize_draft_info(client.post_json(DRAFT_CREATE_INFO,{"draft_id":draft_id},policy=READ_POLICY),candidate,identities)
            except OzonClientError as exc:return self._option(candidate,ValidationState.RATE_LIMITED if exc.code is OzonErrorCode.RATE_LIMITED else ValidationState.UNAVAILABLE,("OZON_RATE_LIMITED" if exc.code is OzonErrorCode.RATE_LIMITED else "OZON_UNAVAILABLE",),draft_id=draft_id)
            except (InvalidDraftResponse,ValueError,TypeError):return self._option(candidate,ValidationState.UNAVAILABLE,("OZON_INVALID_DRAFT_RESPONSE",),draft_id=draft_id)
            if info is not None:break
            if cancelled():return self._option(candidate,ValidationState.UNAVAILABLE,("VALIDATION_CANCELLED",),draft_id=draft_id)
            if attempt+1<MAX_INFO_POLL_ATTEMPTS and self.clock()<deadline:self.sleeper(min(POLL_INTERVAL_SECONDS,max(0,deadline-self.clock())))
        if info is None:return self._option(candidate,ValidationState.UNAVAILABLE,("DRAFT_INFO_TIMEOUT",),draft_id=draft_id)
        causal_reasons=_normalized_reason_codes((*_error_reason_codes(preliminary_errors+info.errors),*preliminary_rejected_reasons,*info.rejected_reason_codes))
        if info.status=="FAILED":return self._option(candidate,ValidationState.REJECTED,("OZON_REJECTED_CANDIDATE",)+causal_reasons,draft_id=draft_id,rejected=info.rejected,warehouses=info.warehouses)
        if not info.accepted:return self._option(candidate,ValidationState.REJECTED,("OZON_REJECTED_CANDIDATE",)+causal_reasons,draft_id=draft_id,rejected=info.rejected,warehouses=info.warehouses)
        try:selected=_selected_warehouses(info.warehouses,identities)
        except InvalidDraftResponse:return self._option(candidate,ValidationState.UNAVAILABLE,("OZON_INVALID_DRAFT_RESPONSE",),draft_id=draft_id,accepted=info.accepted,rejected=info.rejected,warehouses=info.warehouses)
        except ValueError as exc:return self._option(candidate,ValidationState.UNAVAILABLE,(str(exc),),draft_id=draft_id,accepted=info.accepted,rejected=info.rejected,warehouses=info.warehouses)
        if cancelled():return self._option(candidate,ValidationState.UNAVAILABLE,("VALIDATION_CANCELLED",),draft_id=draft_id,accepted=info.accepted,rejected=info.rejected,warehouses=info.warehouses)
        payload={"draft_id":draft_id,"supply_type":create.supply_type,"selected_cluster_warehouses":selected,"date_from":scenario.date_from.isoformat(),"date_to":scenario.date_to.isoformat()}
        try:timeslots=normalize_timeslots(client.post_json(DRAFT_TIMESLOT_INFO,payload,policy=READ_POLICY))
        except TimeslotResponseError as exc:return self._option(candidate,ValidationState.UNAVAILABLE,(str(exc),),draft_id=draft_id,accepted=info.accepted,rejected=info.rejected,warehouses=info.warehouses)
        except OzonClientError as exc:return self._option(candidate,ValidationState.RATE_LIMITED if exc.code is OzonErrorCode.RATE_LIMITED else ValidationState.UNAVAILABLE,("OZON_RATE_LIMITED" if exc.code is OzonErrorCode.RATE_LIMITED else "OZON_UNAVAILABLE",),draft_id=draft_id)
        except (InvalidDraftResponse,ValueError,TypeError):return self._option(candidate,ValidationState.UNAVAILABLE,("OZON_INVALID_DRAFT_RESPONSE",),draft_id=draft_id)
        if info.rejected:return self._option(candidate,ValidationState.PARTIAL,("OZON_PARTIAL_ACCEPTANCE",)+causal_reasons+(("NO_TIMESLOT",) if not timeslots else ()),draft_id=draft_id,accepted=info.accepted,rejected=info.rejected,warehouses=info.warehouses,timeslots=timeslots)
        if not timeslots:return self._option(candidate,ValidationState.NO_TIMESLOT,_normalized_reason_codes((*causal_reasons,"NO_TIMESLOT")),draft_id=draft_id,accepted=info.accepted,warehouses=info.warehouses)
        return self._option(candidate,ValidationState.ACCEPTED,causal_reasons,draft_id=draft_id,accepted=info.accepted,warehouses=info.warehouses,timeslots=timeslots)
