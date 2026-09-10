"""Bounded orchestration for temporary draft validation and live timeslots."""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
import time
from typing import Callable

from backend.shipment.contracts import CandidateAssignment, CandidateShipment, ShipmentScenario
from .client import OzonClientError, OzonRequestPolicy
from .contracts import OzonErrorCode
from .draft_contracts import (OzonRejectedAssignment, OzonTimeslot,
                              OzonWarehouseEvidence, ValidatedShipmentOption,
                              ValidationState)
from .endpoints import DRAFT_CREATE_INFO, DRAFT_TIMESLOT_INFO
from .supply_drafts import CREATE_POLICY, build_draft_create_request

DEFAULT_MAX_NEW_DRAFTS = 6
MAX_INFO_POLL_ATTEMPTS = 5
POLL_INTERVAL_SECONDS = 0.25
MAX_POLL_DURATION_SECONDS = 5.0
VALIDATION_CACHE_TTL_SECONDS = 120.0
VALIDATION_CACHE_MAX_ENTRIES = 64
READ_POLICY = OzonRequestPolicy(retry_safe=True, max_attempts=3)
_TERMINAL = frozenset({"completed", "complete", "success", "ready", "created", "failed", "rejected"})
_PENDING = frozenset({"pending", "processing", "in_progress", "creating"})


class InvalidDraftResponse(ValueError): pass


@dataclass(frozen=True, slots=True)
class _DraftInfo:
    accepted: tuple[CandidateAssignment, ...]
    rejected: tuple[OzonRejectedAssignment, ...]
    warehouses: tuple[OzonWarehouseEvidence, ...]
    travel_days: int | None


def _root(response: object) -> dict:
    if not isinstance(response, dict): raise InvalidDraftResponse
    result = response.get("result", response)
    if not isinstance(result, dict): raise InvalidDraftResponse
    return result


def _draft_id(response: object) -> int | None:
    root = _root(response)
    value = root.get("draft_id")
    if value is None: return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidDraftResponse("invalid draft_id")
    return value


def _records(root: dict, *names: str) -> list:
    for name in names:
        if name in root:
            value = root[name]
            if not isinstance(value, list): raise InvalidDraftResponse(name)
            return value
    return []


def _match(candidate: CandidateShipment, raw: dict) -> CandidateAssignment:
    if not isinstance(raw, dict): raise InvalidDraftResponse
    sku = raw.get("sku")
    cluster = raw.get("destination_cluster_id", raw.get("cluster_id"))
    matches = [row for row in candidate.assignments if row.sku == sku and
               (cluster is None or row.destination_cluster_id == str(cluster))]
    if len(matches) != 1: raise InvalidDraftResponse("assignment identity")
    row = matches[0]
    quantity = raw.get("quantity", raw.get("accepted_quantity", raw.get("rejected_quantity")))
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0 or quantity != row.quantity:
        raise InvalidDraftResponse("assignment quantity")
    article = raw.get("article")
    if article is not None and article != row.article: raise InvalidDraftResponse("article identity")
    return row


def _rejected(candidate: CandidateShipment, rows: list) -> tuple[OzonRejectedAssignment, ...]:
    result = []
    for raw in rows:
        row = _match(candidate, raw)
        error = raw.get("error", {})
        if not isinstance(error, dict): error = {}
        code = raw.get("code", error.get("code", "OZON_REJECTED"))
        message = raw.get("message", error.get("message", ""))
        result.append(OzonRejectedAssignment(row.sku, row.article,
            row.destination_cluster_id, row.quantity, str(code).strip() or "OZON_REJECTED",
            str(message)))
    return tuple(result)


def _warehouse_rows(root: dict, candidate: CandidateShipment) -> tuple[OzonWarehouseEvidence, ...]:
    raw_rows = _records(root, "warehouse_evidence", "warehouses", "storage_warehouses")
    if not raw_rows:
        clusters = root.get("clusters", root.get("clusters_info", []))
        if clusters is not None and not isinstance(clusters, list): raise InvalidDraftResponse
        raw_rows = []
        for cluster in clusters or []:
            if not isinstance(cluster, dict): raise InvalidDraftResponse
            cid = cluster.get("destination_cluster_id", cluster.get("cluster_id"))
            warehouses = cluster.get("warehouses", cluster.get("storage_warehouses", []))
            if not isinstance(warehouses, list): raise InvalidDraftResponse
            raw_rows.extend({**warehouse, "destination_cluster_id": cid}
                            for warehouse in warehouses if isinstance(warehouse, dict))
    result = []
    for raw in raw_rows:
        if not isinstance(raw, dict): raise InvalidDraftResponse
        cid = raw.get("destination_cluster_id", raw.get("cluster_id"))
        wid = raw.get("warehouse_id", raw.get("id"))
        if cid is None or str(cid) not in candidate.cluster_ids or isinstance(wid, bool) or not isinstance(wid, int): raise InvalidDraftResponse
        score = raw.get("score")
        result.append(OzonWarehouseEvidence(str(cid), wid, score))
    return tuple(sorted(set(result), key=lambda x: (x.destination_cluster_id, x.warehouse_id)))


def normalize_draft_info(response: object, candidate: CandidateShipment) -> _DraftInfo | None:
    root = _root(response)
    status = str(root.get("status", "completed")).strip().casefold()
    if status in _PENDING: return None
    if status not in _TERMINAL: raise InvalidDraftResponse("status")
    rejected = _rejected(candidate, _records(root, "rejected_assignments", "rejected_items", "errors"))
    accepted_raw = _records(root, "accepted_assignments", "accepted_items", "items")
    accepted = tuple(_match(candidate, raw) for raw in accepted_raw)
    if not accepted_raw:
        rejected_identity = {(x.sku, x.destination_cluster_id) for x in rejected}
        accepted = tuple(row for row in candidate.assignments
                         if (row.sku, row.destination_cluster_id) not in rejected_identity)
    if sum(x.quantity for x in accepted) + sum(x.quantity for x in rejected) != candidate.total_qty:
        raise InvalidDraftResponse("quantity conservation")
    travel = root.get("travel_time_days")
    if travel is not None and (isinstance(travel, bool) or not isinstance(travel, int) or travel <= 0):
        raise InvalidDraftResponse("travel_time_days")
    return _DraftInfo(accepted, rejected, _warehouse_rows(root, candidate), travel)


def normalize_timeslots(response: object) -> tuple[OzonTimeslot, ...]:
    root = _root(response)
    rows = _records(root, "timeslots", "time_slots", "available_timeslots")
    result = set()
    for raw in rows:
        if not isinstance(raw, dict): raise InvalidDraftResponse
        start = raw.get("from", raw.get("from_dt", raw.get("date_from")))
        end = raw.get("to", raw.get("to_dt", raw.get("date_to")))
        try: slot = OzonTimeslot(datetime.fromisoformat(start), datetime.fromisoformat(end))
        except (TypeError, ValueError) as exc: raise InvalidDraftResponse("timeslot") from exc
        result.add(slot)
    return tuple(sorted(result, key=lambda x: (x.from_dt, x.to_dt)))


class DraftValidationService:
    def __init__(self, client, *, clock: Callable[[], float] = time.monotonic,
                 utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 today: Callable[[], date] = date.today,
                 sleeper: Callable[[float], None] = time.sleep,
                 cache_ttl: float = VALIDATION_CACHE_TTL_SECONDS,
                 cache_size: int = VALIDATION_CACHE_MAX_ENTRIES) -> None:
        self.client=client; self.clock=clock; self.utcnow=utcnow; self.today=today
        self.sleeper=sleeper; self.cache_ttl=cache_ttl; self.cache_size=cache_size
        self._cache: OrderedDict[str, tuple[float, ValidatedShipmentOption]] = OrderedDict()

    def _key(self, candidate, scenario, provenance):
        payload = [candidate.candidate_id, provenance, scenario.date_from.isoformat(), scenario.date_to.isoformat(),
                   [(x.sku,x.article,x.destination_cluster_id,x.quantity) for x in candidate.assignments],
                   candidate.seller_warehouse_id,candidate.handoff_point_id,candidate.handoff_warehouse_type]
        return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

    def _option(self, candidate, state, reason, *, draft_id=None, accepted=(), rejected=(), warehouses=(), travel=None, timeslots=()):
        return ValidatedShipmentOption(candidate.candidate_id,draft_id,state,candidate.method,
            candidate.seller_warehouse_id,candidate.handoff_point_id,tuple(accepted),tuple(rejected),
            tuple(warehouses),travel,tuple(timeslots),self.utcnow().isoformat(),tuple(reason))

    def validate(self, candidates: tuple[CandidateShipment, ...], scenario: ShipmentScenario,
                 *, provenance: str, cancelled: Callable[[], bool] = lambda: False):
        created=0; output=[]
        for candidate in candidates:
            if cancelled(): break
            key=self._key(candidate,scenario,provenance); cached=self._cache.get(key)
            if cached and self.clock()-cached[0] < self.cache_ttl:
                self._cache.move_to_end(key); output.append(cached[1]); continue
            if cached: self._cache.pop(key,None)
            if created >= DEFAULT_MAX_NEW_DRAFTS:
                output.append(self._option(candidate,ValidationState.RATE_LIMITED,("DRAFT_BUDGET_EXHAUSTED",))); continue
            current=self.today()
            if scenario.date_from < current or scenario.date_to > current + timedelta(days=28):
                output.append(self._option(candidate,ValidationState.UNAVAILABLE,("TIMESLOT_DATE_RANGE_UNSUPPORTED",))); continue
            created += 1
            option=self._validate_one(candidate,scenario,cancelled)
            output.append(option)
            self._cache[key]=(self.clock(),option); self._cache.move_to_end(key)
            while len(self._cache)>self.cache_size: self._cache.popitem(last=False)
        return tuple(output)

    def _validate_one(self,candidate,scenario,cancelled):
        try:
            create=build_draft_create_request(candidate)
            response=self.client.post_json(create.path,create.payload,policy=CREATE_POLICY)
            root=_root(response); immediate=_records(root,"rejected_assignments","rejected_items","errors")
            raw_draft_id=root.get("draft_id")
            if immediate and (isinstance(raw_draft_id,bool) or not isinstance(raw_draft_id,int) or raw_draft_id<=0):
                rejected=_rejected(candidate,immediate)
                return self._option(candidate,ValidationState.REJECTED,("OZON_REJECTED_CANDIDATE",),rejected=rejected)
            draft_id=_draft_id(response)
            if draft_id is None:
                raise InvalidDraftResponse("missing draft_id")
        except OzonClientError as exc:
            if exc.code is OzonErrorCode.RATE_LIMITED:
                return self._option(candidate,ValidationState.RATE_LIMITED,("OZON_RATE_LIMITED",))
            if exc.code is OzonErrorCode.UNAVAILABLE and exc.status is None:
                return self._option(candidate,ValidationState.OUTCOME_UNKNOWN,("DRAFT_CREATE_OUTCOME_UNKNOWN",))
            reason="OZON_INVALID_DRAFT_RESPONSE" if exc.code is OzonErrorCode.INVALID_RESPONSE else "OZON_UNAVAILABLE"
            return self._option(candidate,ValidationState.UNAVAILABLE,(reason,))
        except (InvalidDraftResponse, ValueError, TypeError):
            return self._option(candidate,ValidationState.UNAVAILABLE,("OZON_INVALID_DRAFT_RESPONSE",))
        deadline=self.clock()+MAX_POLL_DURATION_SECONDS; info=None
        for attempt in range(MAX_INFO_POLL_ATTEMPTS):
            if attempt and self.clock() >= deadline: break
            if cancelled(): return self._option(candidate,ValidationState.UNAVAILABLE,("VALIDATION_CANCELLED",),draft_id=draft_id)
            try:
                response=self.client.post_json(DRAFT_CREATE_INFO,{"draft_id":draft_id},policy=READ_POLICY)
                info=normalize_draft_info(response,candidate)
            except OzonClientError as exc:
                state=ValidationState.RATE_LIMITED if exc.code is OzonErrorCode.RATE_LIMITED else ValidationState.UNAVAILABLE
                reason="OZON_RATE_LIMITED" if state is ValidationState.RATE_LIMITED else "OZON_UNAVAILABLE"
                return self._option(candidate,state,(reason,),draft_id=draft_id)
            except (InvalidDraftResponse, ValueError, TypeError):
                return self._option(candidate,ValidationState.UNAVAILABLE,("OZON_INVALID_DRAFT_RESPONSE",),draft_id=draft_id)
            if info is not None: break
            if attempt+1 < MAX_INFO_POLL_ATTEMPTS and self.clock() < deadline:
                self.sleeper(min(POLL_INTERVAL_SECONDS,max(0,deadline-self.clock())))
        if info is None:
            return self._option(candidate,ValidationState.UNAVAILABLE,("DRAFT_INFO_TIMEOUT",),draft_id=draft_id)
        if not info.accepted:
            return self._option(candidate,ValidationState.REJECTED,("OZON_REJECTED_CANDIDATE",),draft_id=draft_id,rejected=info.rejected,warehouses=info.warehouses,travel=info.travel_days)
        if not info.warehouses:
            return self._option(candidate,ValidationState.UNAVAILABLE,("OZON_INVALID_DRAFT_RESPONSE",),draft_id=draft_id,accepted=info.accepted,rejected=info.rejected)
        if cancelled(): return self._option(candidate,ValidationState.UNAVAILABLE,("VALIDATION_CANCELLED",),draft_id=draft_id,accepted=info.accepted,rejected=info.rejected)
        payload={"draft_id":draft_id,"supply_type":create.supply_type,
                 "selected_cluster_warehouses":[{"cluster_id":x.destination_cluster_id,"warehouse_id":x.warehouse_id} for x in info.warehouses],
                 "date_from":scenario.date_from.isoformat(),"date_to":scenario.date_to.isoformat()}
        try:
            timeslots=normalize_timeslots(self.client.post_json(DRAFT_TIMESLOT_INFO,payload,policy=READ_POLICY))
        except OzonClientError as exc:
            state=ValidationState.RATE_LIMITED if exc.code is OzonErrorCode.RATE_LIMITED else ValidationState.UNAVAILABLE
            return self._option(candidate,state,("OZON_RATE_LIMITED" if state is ValidationState.RATE_LIMITED else "OZON_UNAVAILABLE",),draft_id=draft_id,accepted=info.accepted,rejected=info.rejected,warehouses=info.warehouses,travel=info.travel_days)
        except (InvalidDraftResponse, ValueError, TypeError):
            return self._option(candidate,ValidationState.UNAVAILABLE,("OZON_INVALID_DRAFT_RESPONSE",),draft_id=draft_id)
        if info.rejected: state=ValidationState.PARTIAL; reasons=("OZON_PARTIAL_ACCEPTANCE",)
        elif not timeslots: state=ValidationState.NO_TIMESLOT; reasons=("NO_TIMESLOT",)
        else: state=ValidationState.ACCEPTED; reasons=()
        return self._option(candidate,state,reasons,draft_id=draft_id,accepted=info.accepted,rejected=info.rejected,warehouses=info.warehouses,travel=info.travel_days,timeslots=timeslots)
