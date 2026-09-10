"""Integrity checks and content-addressed shipment-plan assembly."""
import hashlib, json

from .candidates import _scenario_payload
from .contracts import ShipmentOptionOutcome, ShipmentPlan
from .ranking import rank_outcomes

class ShipmentOrchestrationError(ValueError):
    def __init__(self, code): self.code=code; super().__init__(code)

def scenario_fingerprint(scenario):
    raw=json.dumps(_scenario_payload(scenario),ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return "ss_"+hashlib.sha256(raw.encode()).hexdigest()

def _identity(row): return row.sku,row.destination_cluster_id,row.quantity

def assemble_outcomes(candidates, validations):
    by_id={c.candidate_id:c for c in candidates}; seen=set(); output=[]
    for validation in validations:
        if validation.candidate_id not in by_id or validation.candidate_id in seen:
            raise ShipmentOrchestrationError("VALIDATION_RESULT_IDENTITY_MISMATCH")
        seen.add(validation.candidate_id); candidate=by_id[validation.candidate_id]
        if (validation.method is not candidate.method or
                validation.seller_warehouse_id != candidate.seller_warehouse_id or
                validation.handoff_point_id != candidate.handoff_point_id):
            raise ShipmentOrchestrationError("VALIDATION_RESULT_IDENTITY_MISMATCH")
        remaining=list(candidate.assignments)
        for row in validation.accepted_assignments:
            if row not in remaining: raise ShipmentOrchestrationError("VALIDATION_RESULT_IDENTITY_MISMATCH")
            remaining.remove(row)
        for row in validation.rejected_assignments:
            match=next((item for item in remaining if _identity(item)==_identity(row)),None)
            if match is None: raise ShipmentOrchestrationError("VALIDATION_RESULT_IDENTITY_MISMATCH")
            remaining.remove(match)
        unresolved=tuple(remaining)
        output.append(ShipmentOptionOutcome(candidate,validation,unresolved))
    if seen != set(by_id): raise ShipmentOrchestrationError("VALIDATION_RESULT_IDENTITY_MISMATCH")
    return tuple(output)

def build_shipment_plan(*,source_snapshot_id,analysis_snapshot_id,shippable_plan_id,analysis_as_of,scenario,candidates,validations,diagnostics=()):
    outcomes=assemble_outcomes(candidates,validations); ranked,unavailable=rank_outcomes(outcomes,scenario)
    fingerprint=scenario_fingerprint(scenario)
    evidence=[]
    for o in outcomes:
        v=o.validation
        evidence.append({"candidate_id":v.candidate_id,"draft_id":v.draft_id,"state":v.state.value,
            "checked_at_utc":v.checked_at_utc,"accepted":[_identity(x) for x in v.accepted_assignments],
            "rejected":[_identity(x) for x in v.rejected_assignments],
            "timeslots":[(x.from_dt.isoformat(),x.to_dt.isoformat()) for x in v.timeslots],"reason_codes":v.reason_codes})
    payload=[analysis_snapshot_id,shippable_plan_id,source_snapshot_id,analysis_as_of.isoformat(),fingerprint,evidence]
    plan_id="sp_"+hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return ShipmentPlan(plan_id,source_snapshot_id,analysis_snapshot_id,shippable_plan_id,analysis_as_of,
                        fingerprint,ranked,unavailable,tuple(diagnostics))
