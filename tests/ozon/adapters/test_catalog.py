from backend.ozon.adapters.catalog import V1_CLUSTER_REQUEST, fetch_clusters, normalize_clusters, normalize_seller_warehouses


def v2(): return {"clusters":[{"macrolocal_cluster_id":10,"data":{"macrolocal_cluster":{"name":"Москва"}}}]}
def v1(): return {"clusters":[{"id":77,"macrolocal_cluster_id":10,"name":"Local wrong name","logistic_clusters":[{"warehouses":[{"warehouse_id":501}]}]}]}


def test_v2_owns_macro_identity_and_v1_maps_warehouse_only():
    result=normalize_clusters(v2(),v1())
    assert [(c.cluster_id,c.name) for c in result.clusters]==[(10,"Москва")]
    assert result.warehouse_to_macrolocal=={501:10} and not result.diagnostics


def test_v1_request_has_required_cluster_type():
    class Client:
        def __init__(self): self.calls=[]
        def post_json(self,path,payload,**kwargs): self.calls.append((path,payload)); return v2() if "/v2/" in path else v1()
    client=Client(); result=fetch_clusters(client)
    assert result.warehouse_to_macrolocal=={501:10} and client.calls[1][1]==V1_CLUSTER_REQUEST


def test_generic_local_id_is_not_canonical_macro_identity():
    result=normalize_clusters({"clusters":[{"id":10,"name":"wrong"}]},v1())
    assert result.clusters==() and result.diagnostics[0].code=="INVALID_CLUSTER"


def test_conflicting_warehouse_mapping_remains_blocked_after_matching_observation():
    response = {"clusters": [
        {"macrolocal_cluster_id": 10, "logistic_clusters": [{"warehouses": [{"warehouse_id": 501}]}]},
        {"macrolocal_cluster_id": 20, "logistic_clusters": [{"warehouses": [{"warehouse_id": 501}]}]},
        {"macrolocal_cluster_id": 10, "logistic_clusters": [{"warehouses": [{"warehouse_id": 501}]}]},
    ]}

    result = normalize_clusters(v2(), response)

    assert 501 not in result.warehouse_to_macrolocal
    assert [item.code for item in result.diagnostics].count("CONFLICTING_WAREHOUSE_CLUSTER") == 1


def test_seller_warehouse_strips_contacts_and_conflicts_fail_closed():
    response={"warehouses":[{"warehouse_id":1,"name":"W","address":"A","is_active":True,"phone":"PII"},
                              {"warehouse_id":2,"name":"X","address":"B","is_active":False}]}
    warehouses, diagnostics=normalize_seller_warehouses(response)
    assert not diagnostics and "PII" not in repr(warehouses)
    conflicted, diagnostics=normalize_seller_warehouses({"warehouses":[{"warehouse_id":1,"name":"A","is_active":True},{"warehouse_id":1,"name":"B","is_active":True}]})
    assert conflicted==() and diagnostics[-1].code=="CONFLICTING_SELLER_WAREHOUSE_ID"
