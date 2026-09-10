from datetime import date,datetime,timezone
from decimal import Decimal
from backend.ozon.draft_contracts import OzonTimeslot,ValidatedShipmentOption,ValidationState
from backend.shipment.contracts import CandidateAssignment,CandidateShipment,ShipmentMethod,ShipmentOptionOutcome,ShipmentScenario
from backend.shipment.ranking import rank_outcomes

def assignment(cluster="M",qty=6):return CandidateAssignment("sku","40750",cluster,qty,6,Decimal("1"),Decimal(qty),"normal",("normal",))
def outcome(identity,state,timeslots=(),accepted=True,method=ShipmentMethod.DIRECT,handoff=None):
    row=assignment()
    candidate=CandidateShipment(identity,method,91 if handoff else None,handoff,"PVZ" if handoff else None,("M",),(row,),6,Decimal("6"),())
    validation=ValidatedShipmentOption(identity,1,state,method,91 if handoff else None,handoff,(row,) if accepted else (),(),(),None,timeslots,datetime.now(timezone.utc).isoformat(),())
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

def test_direct_is_not_penalized_against_crossdock_handoff():
    direct=outcome("cs_a",ValidationState.ACCEPTED)
    crossdock=outcome("cs_b",ValidationState.ACCEPTED,method=ShipmentMethod.PVZ_CROSSDOCK,handoff=100)
    ranked,_=rank_outcomes((crossdock,direct),ShipmentScenario(("M",),date(2026,9,10),date(2026,9,11),(ShipmentMethod.DIRECT,ShipmentMethod.PVZ_CROSSDOCK),1,1,91,(100,200)))
    assert [item.option_id for item in ranked]==["cs_a","cs_b"]

def test_handoff_preference_only_orders_crossdock_options():
    first=outcome("cs_a",ValidationState.ACCEPTED,method=ShipmentMethod.PVZ_CROSSDOCK,handoff=100)
    preferred=outcome("cs_b",ValidationState.ACCEPTED,method=ShipmentMethod.PVZ_CROSSDOCK,handoff=200)
    scenario_value=ShipmentScenario(("M",),date(2026,9,10),date(2026,9,11),(ShipmentMethod.PVZ_CROSSDOCK,),1,1,91,(200,100))
    ranked,_=rank_outcomes((first,preferred),scenario_value)
    assert [item.option_id for item in ranked]==["cs_b","cs_a"]

def test_direct_is_not_penalized_against_later_handoff():
    direct=outcome("cs_a",ValidationState.ACCEPTED)
    crossdock=outcome("cs_b",ValidationState.ACCEPTED,method=ShipmentMethod.SC_CROSSDOCK,handoff=300)
    scenario_value=ShipmentScenario(("M",),date(2026,9,10),date(2026,9,11),(ShipmentMethod.DIRECT,ShipmentMethod.SC_CROSSDOCK),1,1,91,(100,200,300))
    ranked,_=rank_outcomes((crossdock,direct),scenario_value)
    assert [item.option_id for item in ranked]==["cs_a","cs_b"]
