from pathlib import Path
from backend.ozon.adapters.stocks import fetch_seller_stock, normalize_fbs_stock
from backend.ozon.endpoints import FBS_STOCK_PATH
def test_zero_and_conflicting_seller_stock_are_separate():
 rows,_=normalize_fbs_stock({'result':{'items':[{'sku':1,'warehouse_id':1,'present':0},{'sku':1,'warehouse_id':2,'present':3},{'sku':1,'warehouse_id':3,'present':4}]}})
 assert [x.fbs_quantity for x in rows]==[0,3,4]
 assert '/v1/product/info/stocks-by-warehouse/fbs' not in Path('backend/ozon/endpoints.py').read_text()


def test_seller_stock_cursor_pagination_preserves_each_warehouse_observation():
 class Client:
  def __init__(self): self.calls=[]
  def post_json(self,path,payload,**kwargs):
   self.calls.append((path,payload))
   if len(self.calls)==1:
    return {'result':{'items':[{'sku':1,'warehouse_id':1,'present':3}],
                      'has_next':True,'cursor':'next'}}
   return {'result':{'items':[{'sku':1,'warehouse_id':2,'present':4}],
                     'has_next':False,'cursor':'done'}}
 client=Client(); rows,diagnostics=fetch_seller_stock(client)
 assert not diagnostics and [row.fbs_quantity for row in rows]==[3,4]
 assert client.calls==[(FBS_STOCK_PATH,{'limit':1000}),
                       (FBS_STOCK_PATH,{'limit':1000,'cursor':'next'})]
