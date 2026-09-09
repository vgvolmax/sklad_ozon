import pytest
from backend.ozon.adapters.products import fetch_product_skus
from backend.ozon.adapters.stocks import fetch_fbo_stock, fetch_seller_stock, normalize_fbo_stock, normalize_fbs_stock
from backend.ozon.endpoints import FBO_STOCK_PATH, FBS_STOCK_PATH, PRODUCT_LIST_PATH


def test_current_fbo_items_use_available_stock_count():
    rows, diagnostics=normalize_fbo_stock({"items":[{"sku":1,"offer_id":"A","name":"P","cluster_id":10,"cluster_name":"Москва","warehouse_id":20,"warehouse_name":"W","available_stock_count":0,"ads":99,"idc":88}]})
    assert not diagnostics and rows[0].fbo_quantity==0


def test_fbo_stock_batches_skus_without_fake_pagination():
    class Client:
        def __init__(self): self.calls=[]
        def post_json(self,path,payload,**kwargs): self.calls.append((path,payload)); return {"items":[]}
    client=Client(); fetch_fbo_stock(client,tuple(str(i) for i in range(201)))
    assert [len(p["skus"]) for _,p in client.calls]==[100,100,1]
    assert all(path==FBO_STOCK_PATH and set(payload)=={"skus"} for path,payload in client.calls)


def test_seller_products_free_stock_and_observations_are_separate():
    rows,_=normalize_fbs_stock({"products":[
        {"sku":1,"offer_id":"A","warehouse_id":1,"warehouse_name":"A","free_stock":3,"present":100,"reserved":0},
        {"sku":1,"offer_id":"A","warehouse_id":2,"warehouse_name":"B","free_stock":4,"present":4,"reserved":4},
        {"sku":1,"offer_id":"A","warehouse_id":3,"warehouse_name":"C","free_stock":0}]})
    assert [x.fbs_quantity for x in rows]==[3,4,0]


def test_seller_stock_top_level_cursor_pagination():
    class Client:
        def __init__(self): self.calls=[]
        def post_json(self,path,payload,**kwargs):
            self.calls.append((path,payload)); n=len(self.calls)
            return {"products":[{"sku":1,"warehouse_id":n,"free_stock":n}],"has_next":n==1,"cursor":"next" if n==1 else "done"}
    client=Client(); rows,diagnostics=fetch_seller_stock(client)
    assert not diagnostics and [r.fbs_quantity for r in rows]==[1,2]
    assert client.calls==[(FBS_STOCK_PATH,{"limit":1000}),(FBS_STOCK_PATH,{"limit":1000,"cursor":"next"})]


def test_product_list_current_pagination_stable_dedupes_and_guards_cursor():
    class Client:
        def __init__(self,repeat=False): self.calls=[]; self.repeat=repeat
        def post_json(self,path,payload,**kwargs):
            self.calls.append((path,payload)); n=len(self.calls)
            return {"result":{"items":[{"sku":2},{"sku":"2"},{"sku":" 3 "},{"sku":""}],"last_id":"next" if n==1 or self.repeat else ""}}
    client=Client(); assert fetch_product_skus(client)==("2","3")
    assert client.calls[0]==(PRODUCT_LIST_PATH,{"filter":{"visibility":"ALL"},"last_id":"","limit":1000})
    with pytest.raises(ValueError,match="non-progressing"): fetch_product_skus(Client(repeat=True))
