from datetime import date,datetime,timezone
from decimal import Decimal
from backend.ozon.draft_contracts import OzonTimeslot,ValidatedShipmentOption,ValidationState
from backend.shipment.contracts import CandidateAssignment,CandidateShipment,ShipmentMethod,ShipmentOptionOutcome,ShipmentScenario
from backend.shipment.ranking import rank_outcomes

def assignment(cluster="M",qty=6):return CandidateAssignment("sku","40750",cluster,qty,6,Decimal("1"),Decimal(qty),"normal",("normal",))
def outcome(identity,state,timeslots=(),accepted=True):
    row=assignment(); candidate=CandidateShipment(identity,ShipmentMethod.DIRECT,None,None,None,("M",),(row,),6,Decimal("6"),())
    validation=ValidatedShipmentOption(identity,1,state,ShipmentMethod.DIRECT,None,None,(row,) if accepted else (),(),(),None,timeslots,datetime.now(timezone.utc).isoformat(),())
    return ShipmentOptionOutcome(candidate,validation,() if accepted else (row,))
def scenario():return ShipmentScenario(("M",),date(2026,9,10),date(2026,9,11),(ShipmentMethod.DIRECT,),1,1)

def test_timeslot_precedes_coverage_and_unavailable_is_preserved():
    slot=(OzonTimeslot(datetime(2026,9,10,tzinfo=timezone.utc),datetime(2026,9,11,tzinfo=timezone.utc)),)
    no_slot=outcome("cs_b",ValidationState.NO_TIMESLOT)
    with_slot=outcome("cs_a",ValidationState.PARTIAL,slot)
    rejected=outcome("cs_c",ValidationState.REJECTED,accepted=False)
    ranked,unavailable=rank_outcomes((no_slot,rejected,with_slot),scenario())
    assert [x.option_id for x in ranked]==["cs_a","cs_b"]
    assert unavailable==(rejected,)
