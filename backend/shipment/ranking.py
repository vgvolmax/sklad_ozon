"""Pure deterministic operational ranking of Ozon validation evidence."""
from decimal import Decimal
from functools import cmp_to_key

from backend.ozon.draft_contracts import ValidationState
from .contracts import RankedShipmentOption, ShipmentOptionOutcome, ShipmentScenario

RANKABLE = {ValidationState.ACCEPTED, ValidationState.PARTIAL, ValidationState.NO_TIMESLOT}

def _preference(point, scenario):
    try: return scenario.selected_handoff_point_ids.index(point)
    except ValueError: return len(scenario.selected_handoff_point_ids)

def _compare(a, b, scenario):
    a_key=(0 if a.accepted_qty else 1,0 if a.has_timeslot else 1,
           -a.accepted_cluster_count,-a.accepted_qty,a.rejected_qty)
    b_key=(0 if b.accepted_qty else 1,0 if b.has_timeslot else 1,
           -b.accepted_cluster_count,-b.accepted_qty,b.rejected_qty)
    if a_key != b_key: return -1 if a_key < b_key else 1
    a_point=a.outcome.candidate.handoff_point_id
    b_point=b.outcome.candidate.handoff_point_id
    if a_point is not None and b_point is not None:
        a_preference=_preference(a_point,scenario); b_preference=_preference(b_point,scenario)
        if a_preference != b_preference: return -1 if a_preference < b_preference else 1
    return (a.option_id > b.option_id) - (a.option_id < b.option_id)

def rank_outcomes(outcomes: tuple[ShipmentOptionOutcome, ...], scenario: ShipmentScenario):
    ranked=[]; unavailable=[]
    for outcome in outcomes:
        validation=outcome.validation
        accepted=validation.accepted_assignments
        if validation.state not in RANKABLE or not accepted:
            unavailable.append(outcome); continue
        accepted_qty=sum(row.quantity for row in accepted)
        rejected_qty=sum(row.quantity for row in validation.rejected_assignments)
        reasons=["OZON_ACCEPTED_ASSIGNMENTS",
                 "CURRENT_TIMESLOT_AVAILABLE" if validation.timeslots else "CURRENT_TIMESLOT_UNAVAILABLE"]
        if validation.state is ValidationState.PARTIAL: reasons.append("OZON_PARTIAL_ACCEPTANCE")
        if outcome.candidate.handoff_point_id is not None: reasons.append("USER_HANDOFF_PREFERENCE")
        ranked.append(RankedShipmentOption(
            outcome.candidate.candidate_id,outcome,accepted_qty,rejected_qty,
            len({x.destination_cluster_id for x in accepted}),len({x.sku for x in accepted}),
            sum((x.total_volume_l for x in accepted),Decimal("0")),bool(validation.timeslots),tuple(reasons)))
    ranked.sort(key=cmp_to_key(lambda a,b:_compare(a,b,scenario)))
    return tuple(ranked),tuple(unavailable)
