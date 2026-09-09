import pytest

from backend.ozon.adapters.inbound import (SupplyState, _fetch_bundles, _fetch_order_ids,
                                           classify_supply_state, fetch_inbound, normalize_inbound)
from backend.ozon.endpoints import SUPPLY_ORDER_BUNDLE_PATH, SUPPLY_ORDER_GET_PATH, SUPPLY_ORDER_LIST_PATH


@pytest.mark.parametrize(("raw", "expected"), [
    ("IN_TRANSIT", SupplyState.INBOUND), ("COMPLETED", SupplyState.FINAL),
    ("CANCELLED", SupplyState.FINAL), ("NEW_FUTURE_STATE", SupplyState.UNKNOWN),
])
def test_documented_state_classifier(raw, expected):
    assert classify_supply_state(raw) is expected


def test_normalization_uses_macro_cluster_id_bundle_id_and_fails_closed():
    details = [{"order_id": 7, "supplies": [
        {"state": "IN_TRANSIT", "macrolocal_cluster_id": 10, "bundle_id": 99},
        {"state": "COMPLETED", "macrolocal_cluster_id": 10, "bundle_id": 100},
        {"state": "UNKNOWN", "macrolocal_cluster_id": 10, "bundle_id": 101},
        {"state": "IN_TRANSIT", "macrolocal_cluster_id": 999, "bundle_id": 102},
    ]}]
    records, diagnostics = normalize_inbound(details, {99: [{"sku": "S", "quantity": 3}]}, {10: "Москва"})
    assert [(row.sku, row.cluster, row.inbound_quantity) for row in records] == [("S", "Москва", 3)]
    assert {item.code for item in diagnostics} == {"UNKNOWN_SUPPLY_STATE", "UNRESOLVED_SUPPLY_CLUSTER"}


class Client:
    def __init__(self): self.calls = []
    def post_json(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        if path == SUPPLY_ORDER_LIST_PATH:
            return {"order_ids": [7], "last_id": ""}
        if path == SUPPLY_ORDER_GET_PATH:
            return {"orders": [{"order_id": 7, "supplies": [
                {"state": "IN_TRANSIT", "macrolocal_cluster_id": 10, "bundle_id": 99}]}]}
        if path == SUPPLY_ORDER_BUNDLE_PATH:
            return {"bundles": [{"bundle_id": 99, "items": [{"sku": "S", "quantity": 4}]}],
                    "has_next": False}
        raise AssertionError(path)


def test_wire_requests_use_order_ids_then_bundle_ids():
    client = Client()
    records, diagnostics = fetch_inbound(client, {10: "Москва"})
    assert records[0].inbound_quantity == 4 and not diagnostics
    assert client.calls[0][1] == {"filter": {}, "limit": 100, "sort_by": "ORDER_CREATION"}
    assert client.calls[1][1] == {"order_ids": [7]}
    assert client.calls[2][1] == {"bundle_ids": [99], "limit": 1000}
    assert all("order_id" not in payload and "supply_order_id" not in payload for _, payload in client.calls)


def test_final_supply_does_not_double_count_current_fbo():
    records, diagnostics = normalize_inbound(
        [{"order_id": 7, "supplies": [{"state": "COMPLETED", "macrolocal_cluster_id": 10, "bundle_id": 99}]}],
        {99: [{"sku": "S", "quantity": 4}]}, {10: "Москва"})
    assert records == () and diagnostics == ()


def test_supply_list_last_id_paginates_two_pages():
    class PagedClient:
        def __init__(self): self.calls = []
        def post_json(self, path, payload, **kwargs):
            self.calls.append(payload)
            return ({"order_ids": list(range(100)), "last_id": "next"}
                    if len(self.calls) == 1 else {"order_ids": [100], "last_id": ""})
    client = PagedClient()
    assert _fetch_order_ids(client) == list(range(101))
    assert client.calls[1]["last_id"] == "next"


def test_bundle_last_id_paginates_two_pages_without_order_identity_substitution():
    class PagedClient:
        def __init__(self): self.calls = []
        def post_json(self, path, payload, **kwargs):
            self.calls.append(payload)
            if len(self.calls) == 1:
                return {"bundles": [{"bundle_id": 99, "items": [{"sku": "S", "quantity": 2}]}],
                        "has_next": True, "last_id": "next"}
            return {"bundles": [{"bundle_id": 99, "items": [{"sku": "S", "quantity": 3}]}],
                    "has_next": False}
    client = PagedClient()
    assert _fetch_bundles(client, [99])[99] == [{"sku": "S", "quantity": 2},
                                                 {"sku": "S", "quantity": 3}]
    assert client.calls[1] == {"bundle_ids": [99], "limit": 1000, "last_id": "next"}
