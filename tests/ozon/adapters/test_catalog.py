from backend.ozon.adapters.catalog import normalize_seller_warehouses
def test_seller_catalog_strips_contacts():
 rows,diags=normalize_seller_warehouses({'result':{'warehouses':[{'warehouse_id':1,'name':'W','address':'A','is_active':True,'contacts':'SECRET'}]}})
 assert rows[0].seller_warehouse_id==1 and 'SECRET' not in repr(rows) and not diags
