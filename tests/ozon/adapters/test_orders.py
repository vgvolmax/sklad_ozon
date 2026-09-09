from backend.ozon.adapters.orders import normalize_posting
def test_order_normalization_discards_pii_and_keeps_destination():
 records=normalize_posting({'status':'delivered','buyer':{'phone':'SECRET'},'analytics_data':{'warehouse':'M','region':'K'},'products':[{'sku':1,'offer_id':'A','name':'N','quantity':2}]})
 assert records[0].destination_cluster=='K' and records[0].quantity==2 and 'SECRET' not in repr(records)
