"""Pure deterministic operational ranking of Ozon validation evidence."""
from decimal import Decimal

from backend.ozon.draft_contracts import ValidationState
from .contracts import RankedShipmentOption, ShipmentOptionOutcome, ShipmentScenario

RANKABLE = {ValidationState.ACCEPTED, ValidationState.PARTIAL, ValidationState.NO_TIMESLOT}

def _preference(outcome, scenario):
    point = outcome.candidate.handoff_point_id
    if point is None:
        return len(scenario.selected_handoff_point_ids)
    try: return scenario.selected_handoff_point_ids.index(point)
    except ValueError: return len(scenario.selected_handoff_point_ids) + 1

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
    ranked.sort(key=lambda x:(0 if x.accepted_qty else 1,0 if x.has_timeslot else 1,
        -x.accepted_cluster_count,-x.accepted_qty,x.rejected_qty,
        _preference(x.outcome,scenario),x.option_id))
    return tuple(ranked),tuple(unavailable)
