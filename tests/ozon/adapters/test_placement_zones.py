from backend.ozon.adapters.placement_zones import fetch_placement_zones, normalize_placement_zones
from backend.ozon.endpoints import PLACEMENT_ZONE_PATH


def test_current_products_placement_exact_and_unknown():
    rows, diagnostics=normalize_placement_zones({"products_placement":[{"sku":"S","placement_zone":"FRESH"},{"sku":"X","placement_zone":"UNSPECIFIED"},{"sku":"B","placement_zone":""}]})
    assert rows[0].zones==("FRESH",) and rows[0].complete
    assert rows[1].zones==("UNSPECIFIED",) and not rows[1].complete
    assert rows[2].zones==() and len(diagnostics)==2


def test_request_uses_bounded_sku_batches():
    class Client:
        def __init__(self): self.calls=[]
        def post_json(self,path,payload,**kwargs): self.calls.append((path,payload)); return {"products_placement":[]}
    client=Client(); fetch_placement_zones(client,tuple(str(i) for i in range(201)))
    assert [len(payload["skus"]) for _,payload in client.calls]==[100,100,1]
    assert all(path==PLACEMENT_ZONE_PATH and set(payload)=={"skus"} for path,payload in client.calls)
