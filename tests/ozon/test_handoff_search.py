import pytest
from backend.ozon.handoff import HandoffPointStore,search_handoff_points
class Client:
 def __init__(self): self.calls=[]
 def post_json(self,*args,**kwargs): self.calls.append(args); return {'result':{'warehouses':[{'warehouse_id':1,'name':'N','warehouse_type':'PVZ'}]}}
def test_short_query_never_calls_network_and_results_are_ephemeral():
 client=Client()
 with pytest.raises(ValueError): search_handoff_points(client,' abc ',())
 assert not client.calls
 points=search_handoff_points(client,' abcd ',('FBO',)); store=HandoffPointStore(); store.put_all(points)
 assert store.require(1).warehouse_type=='PVZ' and HandoffPointStore().get(1) is None
