from backend.ozon.adapters.inbound import SupplyState,classify_supply_state,normalize_inbound_bundles
def test_only_active_supply_is_inbound_and_unknown_is_incomplete():
 assert classify_supply_state('completed') is SupplyState.FINAL
 assert classify_supply_state('new-future-state') is SupplyState.UNKNOWN
 rows,diags=normalize_inbound_bundles([{'id':1,'status':'in_transit','warehouse_id':9},{'id':2,'status':'mystery','warehouse_id':9}],{1:[{'sku':'S','quantity':2}]},{9:'C'})
 assert rows[0].inbound_quantity==2 and diags[0].code=='UNKNOWN_SUPPLY_STATE'
