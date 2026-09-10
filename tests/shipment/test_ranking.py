from dataclasses import replace
from datetime import date,datetime,timezone
from decimal import Decimal
from itertools import permutations
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

def test_mixed_method_handoff_order_is_permutation_invariant():
    options=(
        outcome("cs_a",ValidationState.ACCEPTED,method=ShipmentMethod.PVZ_CROSSDOCK,handoff=100),
        outcome("cs_b",ValidationState.ACCEPTED),
        outcome("cs_c",ValidationState.ACCEPTED,method=ShipmentMethod.SC_CROSSDOCK,handoff=200),
    )
    scenario_value=ShipmentScenario(("M",),date(2026,9,10),date(2026,9,11),
        (ShipmentMethod.DIRECT,ShipmentMethod.PVZ_CROSSDOCK,ShipmentMethod.SC_CROSSDOCK),
        1,1,91,(200,100))
    for ordering in permutations(options):
        ranked,_=rank_outcomes(ordering,scenario_value)
        assert tuple(item.option_id for item in ranked)==("cs_c","cs_b","cs_a")

def test_larger_mixed_method_bucket_has_stable_handoff_slots():
    options=(
        outcome("cs_a",ValidationState.ACCEPTED),
        outcome("cs_b",ValidationState.ACCEPTED,method=ShipmentMethod.PVZ_CROSSDOCK,handoff=300),
        outcome("cs_c",ValidationState.ACCEPTED),
        outcome("cs_d",ValidationState.ACCEPTED,method=ShipmentMethod.SC_CROSSDOCK,handoff=100),
        outcome("cs_e",ValidationState.ACCEPTED,method=ShipmentMethod.PVZ_CROSSDOCK,handoff=200),
    )
    scenario_value=ShipmentScenario(("M",),date(2026,9,10),date(2026,9,11),
        (ShipmentMethod.DIRECT,ShipmentMethod.PVZ_CROSSDOCK,ShipmentMethod.SC_CROSSDOCK),
        1,1,91,(200,100,300))
    expected=("cs_a","cs_e","cs_c","cs_d","cs_b")
    for ordering in (options,options[::-1],options[2:]+options[:2],(options[4],options[0],options[3],options[1],options[2])):
        ranked,_=rank_outcomes(ordering,scenario_value)
        assert tuple(item.option_id for item in ranked)==expected

def test_timeslot_operational_bucket_dominates_handoff_preference():
    slot=(OzonTimeslot(datetime(2026,9,10,tzinfo=timezone.utc),datetime(2026,9,11,tzinfo=timezone.utc)),)
    preferred=outcome("cs_a",ValidationState.NO_TIMESLOT,
        method=ShipmentMethod.PVZ_CROSSDOCK,handoff=200)
    direct=outcome("cs_b",ValidationState.ACCEPTED,slot)
    scenario_value=ShipmentScenario(("M",),date(2026,9,10),date(2026,9,11),
        (ShipmentMethod.DIRECT,ShipmentMethod.PVZ_CROSSDOCK),1,1,91,(200,))
    ranked,_=rank_outcomes((preferred,direct),scenario_value)
    assert tuple(item.option_id for item in ranked)==("cs_b","cs_a")

def test_accepted_cluster_coverage_dominates_handoff_preference():
    preferred=outcome("cs_a",ValidationState.ACCEPTED,
        method=ShipmentMethod.PVZ_CROSSDOCK,handoff=200)
    less_preferred=outcome("cs_b",ValidationState.ACCEPTED,
        method=ShipmentMethod.PVZ_CROSSDOCK,handoff=100)
    second_row=assignment("K",6)
    candidate=replace(less_preferred.candidate,cluster_ids=("M","K"),
        assignments=less_preferred.candidate.assignments+(second_row,),total_qty=12,
        total_volume_l=Decimal("12"))
    validation=replace(less_preferred.validation,
        accepted_assignments=less_preferred.validation.accepted_assignments+(second_row,))
    less_preferred=replace(less_preferred,candidate=candidate,validation=validation)
    scenario_value=ShipmentScenario(("M","K"),date(2026,9,10),date(2026,9,11),
        (ShipmentMethod.PVZ_CROSSDOCK,),2,2,91,(200,100))
    ranked,_=rank_outcomes((preferred,less_preferred),scenario_value)
    assert tuple(item.option_id for item in ranked)==("cs_b","cs_a")
