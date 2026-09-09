from pathlib import Path
from backend.ozon.adapters.stocks import normalize_fbs_stock
def test_zero_and_conflicting_seller_stock_are_separate():
 rows,_=normalize_fbs_stock({'result':{'items':[{'sku':1,'warehouse_id':1,'present':0},{'sku':1,'warehouse_id':2,'present':3},{'sku':1,'warehouse_id':3,'present':4}]}})
 assert [x.fbs_quantity for x in rows]==[0,3,4]
 assert '/v1/product/info/stocks-by-warehouse/fbs' not in Path('backend/ozon/endpoints.py').read_text()
