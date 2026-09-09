from backend.ozon.adapters.catalog import V1_CLUSTER_REQUEST, fetch_clusters, normalize_clusters, normalize_seller_warehouses


def v2(cluster_id=10, name="Москва"):
    return {"clusters": [{"macrolocal_cluster_id": cluster_id,
                           "data": {"macrolocal_cluster": {"name": name}}}]}


def test_v2_nested_contract_uses_macrolocal_identity_only():
    clusters, diagnostics = normalize_clusters(v2())
    assert clusters[0].cluster_id == 10 and clusters[0].name == "Москва"
    assert not diagnostics
    generic, diagnostics = normalize_clusters({"clusters": [{"id": 10, "name": "wrong"}]})
    assert not generic and diagnostics[0].code == "INVALID_CLUSTER"


def test_v1_request_has_required_cluster_type():
    class Client:
        def __init__(self): self.calls = []
        def post_json(self, path, payload, **kwargs):
            self.calls.append((path, payload))
            return v2() if path.endswith("v2/cluster/list") else {"clusters": []}
    client = Client()
    fetch_clusters(client)
    assert client.calls[1][1] == V1_CLUSTER_REQUEST


def test_conflicting_id_removes_affected_catalog_identity():
    clusters, diagnostics = normalize_clusters(v2(), {"clusters": [{"cluster_id": 10, "name": "Other"}]})
    assert clusters == ()
    assert diagnostics[-1].code == "CONFLICTING_CLUSTER_ID"


def test_seller_warehouse_strips_contacts_and_conflicts_fail_closed():
    response = {"warehouses": [
        {"warehouse_id": 1, "name": "W", "address": "A", "is_active": True,
         "is_pickup": False, "phone": "PII", "courier_comment": "PII"},
        {"warehouse_id": 2, "name": "X", "address": "B", "is_active": False},
    ]}
    warehouses, diagnostics = normalize_seller_warehouses(response)
    assert not diagnostics and warehouses[0].seller_warehouse_id == 1
    assert "PII" not in repr(warehouses)
    conflicted, diagnostics = normalize_seller_warehouses({"warehouses": [
        {"warehouse_id": 1, "name": "A", "is_active": True},
        {"warehouse_id": 1, "name": "B", "is_active": True},
    ]})
    assert conflicted == () and diagnostics[-1].code == "CONFLICTING_SELLER_WAREHOUSE_ID"
