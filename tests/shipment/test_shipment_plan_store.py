from datetime import date
from backend.shipment.contracts import ShipmentPlan
from backend.shipment.store import ShipmentPlanStore

def plan(identity): return ShipmentPlan(identity,None,"a","p",date(2026,9,10),"ss_x",(),(),())

def test_store_is_bounded_and_clearable():
    store=ShipmentPlanStore(2)
    store.put(plan("sp_1"));store.put(plan("sp_2"));store.put(plan("sp_3"))
    assert store.get("sp_1") is None and store.get("sp_3") is not None
    store.clear();assert len(store)==0
