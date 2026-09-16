import pytest

from backend.ozon.adapters.inbound import (
    PAGE_SIZE, SUPPLY_ORDER_STATES,
    SupplyState,
    _fetch_bundles,
    _fetch_details,
    _fetch_order_ids,
    classify_supply_state,
    fetch_inbound,
    normalize_inbound,
)
from backend.ozon.endpoints import (
    SUPPLY_ORDER_BUNDLE_PATH,
    SUPPLY_ORDER_GET_PATH,
    SUPPLY_ORDER_LIST_PATH,
)
from backend.ozon.source_contracts import OzonRecordQualityEvidence

UUID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.parametrize(("raw", "expected"), [
    ("IN_TRANSIT", SupplyState.INBOUND),
    ("COMPLETED", SupplyState.FINAL),
    ("REPORT_REJECTED", SupplyState.DISPUTED),
    ("NEW_FUTURE_STATE", SupplyState.UNKNOWN),
])
def test_state_classifier(raw, expected):
    assert classify_supply_state(raw) is expected


def _normalize(supplies, bundles, clusters=None, mapping=None):
    return normalize_inbound(
        [{"order_id": 7, "supplies": supplies}], bundles,
        clusters or {10: "Москва"}, mapping or {})


def test_direct_macrolocal_cluster_works_without_warehouse_mapping():
    rows, diagnostics, quality = _normalize([{
        "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
        "storage_warehouse": {"warehouse_id": 999}, "bundle_id": UUID,
    }], {UUID: [{"sku": "S", "quantity": 3}]})

    assert [(row.sku, row.cluster, row.inbound_quantity) for row in rows] == [
        ("S", "Москва", 3)]
    assert not diagnostics
    assert quality.rejected_record_count == 0


def test_warehouse_mapping_remains_absent_direct_id_fallback():
    rows, diagnostics, _quality = _normalize([{
        "state": "IN_TRANSIT", "storage_warehouse": {"warehouse_id": 501},
        "bundle_id": UUID,
    }], {UUID: [{"sku": "S", "quantity": 3}]}, mapping={501: 10})
    assert rows[0].cluster == "Москва"
    assert not diagnostics


def test_direct_cluster_beats_conflicting_warehouse_fallback():
    rows, diagnostics, _quality = _normalize([{
        "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
        "storage_warehouse": {"warehouse_id": 501}, "bundle_id": UUID,
    }], {UUID: [{"sku": "S", "quantity": 3}]},
        clusters={10: "Москва", 20: "Казань"}, mapping={501: 20})
    assert rows[0].cluster == "Москва"
    assert not diagnostics


@pytest.mark.parametrize(("direct", "code"), [
    (999, "UNRESOLVED_SUPPLY_CLUSTER"),
    (True, "INVALID_SUPPLY_MACROLOCAL_CLUSTER_ID"),
    (-1, "INVALID_SUPPLY_MACROLOCAL_CLUSTER_ID"),
    ("10", "INVALID_SUPPLY_MACROLOCAL_CLUSTER_ID"),
    ([], "INVALID_SUPPLY_MACROLOCAL_CLUSTER_ID"),
])
def test_explicit_invalid_direct_cluster_is_not_hidden_by_fallback(direct, code):
    rows, diagnostics, _quality = _normalize([{
        "state": "IN_TRANSIT", "macrolocal_cluster_id": direct,
        "storage_warehouse": {"warehouse_id": 501}, "bundle_id": UUID,
    }], {UUID: [{"sku": "S", "quantity": 3}]}, mapping={501: 10})
    assert rows == ()
    assert [item.code for item in diagnostics] == [code]


def test_disputed_supply_is_scoped_unknown_and_quantity_is_not_counted():
    rows, diagnostics, quality = _normalize([{
        "state": "REPORT_REJECTED", "macrolocal_cluster_id": 10,
        "bundle_id": UUID,
    }], {UUID: [{"sku": "SKU-B", "quantity": 3}]})
    assert rows == ()
    assert quality.rejected_record_count == 1
    assert quality.incomplete_skus == ("SKU-B",)
    assert [(item.code, item.severity) for item in diagnostics] == [
        ("REPORT_REJECTED_SUPPLY_STATE", "warning")]


def test_disputed_and_normal_supply_preserve_only_clean_observation():
    disputed = "disputed"
    rows, diagnostics, quality = _normalize([
        {"state": "IN_TRANSIT", "macrolocal_cluster_id": 10, "bundle_id": UUID},
        {"state": "REPORT_REJECTED", "macrolocal_cluster_id": 10,
         "bundle_id": disputed},
    ], {
        UUID: [{"sku": "SKU-B", "quantity": 5}],
        disputed: [{"sku": "SKU-B", "quantity": 3}],
    })
    assert [(row.sku, row.inbound_quantity) for row in rows] == [("SKU-B", 5)]
    assert quality.incomplete_skus == ("SKU-B",)
    assert {item.code for item in diagnostics} == {"REPORT_REJECTED_SUPPLY_STATE"}


def test_disputed_multiple_items_have_deterministic_unique_skus():
    _rows, _diagnostics, quality = _normalize([{
        "state": "REPORT_REJECTED", "bundle_id": UUID,
    }], {UUID: [
        {"sku": "B", "quantity": 1}, {"sku": "A", "quantity": 2},
        {"sku": "B", "quantity": 3},
    ]})
    assert quality.rejected_record_count == 3
    assert quality.incomplete_skus == ("A", "B")


def test_disputed_without_bundle_is_global_failure():
    with pytest.raises(ValueError, match="bundle ID"):
        _normalize([{
            "state": "REPORT_REJECTED", "macrolocal_cluster_id": 10,
        }], {})


def test_disputed_supply_with_empty_bundle_fails_closed():
    rows, diagnostics, quality = _normalize([{
        "state": "REPORT_REJECTED", "macrolocal_cluster_id": 10,
        "bundle_id": UUID,
    }], {UUID: []})

    assert rows == ()
    assert quality.incomplete_skus == ()
    assert quality.rejected_record_count == 0
    assert any(
        item.code == "MISSING_SUPPLY_BUNDLE_ITEMS" and item.severity == "error"
        for item in diagnostics
    )
    assert not any(
        item.code == "REPORT_REJECTED_SUPPLY_STATE"
        for item in diagnostics
    )


def test_inbound_supply_with_empty_bundle_fails_closed():
    rows, diagnostics, quality = _normalize([{
        "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
        "bundle_id": UUID,
    }], {UUID: []})

    assert rows == ()
    assert quality.incomplete_skus == ()
    assert any(
        item.code == "MISSING_SUPPLY_BUNDLE_ITEMS" and item.severity == "error"
        for item in diagnostics
    )


def test_inbound_supply_with_missing_bundle_mapping_fails_closed():
    rows, diagnostics, quality = _normalize([{
        "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
        "bundle_id": UUID,
    }], {})

    assert rows == ()
    assert quality.incomplete_skus == ()
    assert [(item.code, item.severity) for item in diagnostics] == [
        ("MISSING_SUPPLY_BUNDLE_ITEMS", "error")]


def test_final_supply_with_empty_bundle_is_ignored():
    rows, diagnostics, quality = _normalize([{
        "state": "COMPLETED", "bundle_id": UUID,
    }], {UUID: []})

    assert rows == ()
    assert diagnostics == ()
    assert quality == OzonRecordQualityEvidence()


def test_nonempty_bundle_with_unknown_sku_is_global_failure():
    with pytest.raises(ValueError, match="SKU"):
        _normalize([{
            "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
            "bundle_id": UUID,
        }], {UUID: [{"sku": "", "quantity": 3}]})


class Client:
    def __init__(self):
        self.calls = []

    def post_json(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        if path == SUPPLY_ORDER_LIST_PATH:
            return {"order_ids": [7], "last_id": ""}
        if path == SUPPLY_ORDER_GET_PATH:
            return {"orders": [{"order_id": 7, "supplies": [{
                "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
                "storage_warehouse": {"warehouse_id": 999}, "bundle_id": UUID,
            }]}]}
        if path == SUPPLY_ORDER_BUNDLE_PATH:
            return {"items": [{"sku": "S", "quantity": 4}],
                    "total_count": 1, "has_next": False, "last_id": ""}
        raise AssertionError(path)


def test_wire_requests_preserve_opaque_bundle_id():
    client = Client()
    rows, diagnostics, quality = fetch_inbound(client, {10: "Москва"}, {})
    assert rows[0].inbound_quantity == 4 and not diagnostics
    assert quality.incomplete_skus == ()
    assert client.calls[1][1] == {"order_ids": [7]}
    assert client.calls[2][1] == {"bundle_ids": [UUID], "limit": 100}


def test_bundle_top_level_items_paginate_one_bundle_at_a_time():
    class Paged:
        def __init__(self):
            self.calls = []

        def post_json(self, path, payload, **kwargs):
            self.calls.append(payload)
            return {"items": [{"sku": "S", "quantity": len(self.calls)}],
                    "has_next": len(self.calls) == 1, "last_id": "next"}

    client = Paged()
    result = _fetch_bundles(client, [UUID, "other"])
    assert result[UUID] == [{"sku": "S", "quantity": 1},
                            {"sku": "S", "quantity": 2}]
    assert client.calls[1] == {"bundle_ids": [UUID], "limit": 100,
                               "last_id": "next"}
    assert client.calls[2]["bundle_ids"] == ["other"]


def test_supply_list_last_id_paginates():
    class Paged:
        def __init__(self):
            self.calls = []

        def post_json(self, path, payload, **kwargs):
            self.calls.append(payload)
            return {"order_ids": [len(self.calls)],
                    "last_id": "next" if len(self.calls) == 1 else ""}

    client = Paged()
    assert _fetch_order_ids(client) == [1, 2]
    assert len(client.calls) == 2
    assert client.calls[1]["last_id"] == "next"
    for payload in client.calls:
        assert payload["filter"]["states"] == list(SUPPLY_ORDER_STATES)
        assert payload["filter"] != {}
        assert payload["limit"] == PAGE_SIZE
        assert 0 < payload["limit"] <= 100
        assert payload["sort_by"] == "ORDER_CREATION"
        assert payload["sort_dir"] == "DESC"


@pytest.mark.parametrize("returned", [
    [{"order_id": 7}],
    [{"order_id": 7}, {"order_id": 7}],
    [{"order_id": 7}, {"order_id": 9}],
])
def test_supply_details_must_exactly_match_requested_ids(returned):
    class DetailsClient:
        def post_json(self, _path, _payload, **_kwargs):
            return {"orders": returned}

    with pytest.raises(ValueError, match="detail|match|duplicate"):
        _fetch_details(DetailsClient(), [7, 8])


class StaticClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def post_json(self, _path, _payload, **_kwargs):
        return next(self.responses)


@pytest.mark.parametrize("response", [
    {}, {"order_ids": None}, {"order_ids": {}}, {"order_ids": "7"},
])
def test_supply_list_requires_order_ids_array(response):
    with pytest.raises(ValueError, match="order_ids"):
        _fetch_order_ids(StaticClient([response]))


def test_supply_list_explicit_empty_is_valid():
    assert _fetch_order_ids(StaticClient([{"order_ids": []}])) == []


@pytest.mark.parametrize("value", [True, 1.5, "7", {}, [], 0, -1])
def test_supply_list_requires_strict_positive_integer_ids(value):
    with pytest.raises(ValueError, match="order ID"):
        _fetch_order_ids(StaticClient([{"order_ids": [value]}]))


def test_supply_list_rejects_duplicate_ids_across_pages():
    client = StaticClient([
        {"order_ids": [7], "last_id": "next"},
        {"order_ids": [7], "last_id": ""},
    ])
    with pytest.raises(ValueError, match="duplicate"):
        _fetch_order_ids(client)


@pytest.mark.parametrize("cursor", [True, 1, [], {}])
def test_supply_list_rejects_wrong_type_cursor(cursor):
    with pytest.raises(ValueError, match="cursor"):
        _fetch_order_ids(StaticClient([{"order_ids": [], "last_id": cursor}]))


def test_supply_list_rejects_repeated_cursor():
    client = StaticClient([
        {"order_ids": [7], "last_id": "next"},
        {"order_ids": [8], "last_id": "next"},
    ])
    with pytest.raises(ValueError, match="cursor"):
        _fetch_order_ids(client)


@pytest.mark.parametrize("response", [
    {}, {"orders": None}, {"orders": {}}, {"orders": "bad"},
])
def test_details_require_orders_array(response):
    with pytest.raises(ValueError, match="orders"):
        _fetch_details(StaticClient([response]), [7])


@pytest.mark.parametrize("orders", [
    [None], [{"order_id": True}], [{"order_id": 7.0}],
    [{"order_id": "7"}], [{"order_id": 0}],
])
def test_details_require_objects_and_strict_ids(orders):
    with pytest.raises(ValueError, match="detail|order ID"):
        _fetch_details(StaticClient([{"orders": orders}]), [7])


@pytest.mark.parametrize("supplies", [pytest.param(None, id="null"), {}, "bad", 123])
def test_normalize_requires_supplies_array(supplies):
    with pytest.raises(ValueError, match="supplies"):
        normalize_inbound([{"order_id": 7, "supplies": supplies}], {}, {}, {})


def test_normalize_rejects_missing_supplies_and_non_object_supply():
    with pytest.raises(ValueError, match="supplies"):
        normalize_inbound([{"order_id": 7}], {}, {}, {})
    with pytest.raises(ValueError, match="supply"):
        _normalize([None], {})


def test_explicit_empty_supplies_is_valid():
    assert _normalize([], {}) == ((), (), OzonRecordQualityEvidence())


@pytest.mark.parametrize("response", [
    {}, {"items": None, "has_next": False},
    {"items": {}, "has_next": False}, {"items": "bad", "has_next": False},
    {"items": [None], "has_next": False},
])
def test_bundle_requires_items_array_of_objects(response):
    with pytest.raises(ValueError, match="items|item"):
        _fetch_bundles(StaticClient([response]), [UUID])


@pytest.mark.parametrize("value", [None, 0, 1, "false", {}, []])
def test_bundle_requires_boolean_has_next(value):
    response = {"items": [], "has_next": value}
    if value is None:
        response.pop("has_next")
    with pytest.raises(ValueError, match="has_next"):
        _fetch_bundles(StaticClient([response]), [UUID])


@pytest.mark.parametrize("cursor", [None, "", "   ", True, 1, [], {}])
def test_bundle_next_page_requires_strict_nonblank_cursor(cursor):
    response = {"items": [{"sku": "S", "quantity": 1}],
                "has_next": True, "last_id": cursor}
    with pytest.raises(ValueError, match="cursor"):
        _fetch_bundles(StaticClient([response]), [UUID])


def test_bundle_rejects_repeated_cursor():
    page = {"items": [{"sku": "S", "quantity": 1}],
            "has_next": True, "last_id": "next"}
    with pytest.raises(ValueError, match="cursor"):
        _fetch_bundles(StaticClient([page, page]), [UUID])


def test_bundle_validates_total_count_across_pages_and_at_terminal_page():
    valid = StaticClient([
        {"items": [{"sku": "A", "quantity": 1}], "total_count": 2,
         "has_next": True, "last_id": "next"},
        {"items": [{"sku": "B", "quantity": 2}], "total_count": 2,
         "has_next": False},
    ])
    assert len(_fetch_bundles(valid, [UUID])[UUID]) == 2

    inconsistent = StaticClient([
        {"items": [{"sku": "A", "quantity": 1}], "total_count": 2,
         "has_next": True, "last_id": "next"},
        {"items": [{"sku": "B", "quantity": 2}], "total_count": 3,
         "has_next": False},
    ])
    with pytest.raises(ValueError, match="total_count"):
        _fetch_bundles(inconsistent, [UUID])

    mismatch = StaticClient([{
        "items": [{"sku": "A", "quantity": 1}], "total_count": 2,
        "has_next": False,
    }])
    with pytest.raises(ValueError, match="total_count"):
        _fetch_bundles(mismatch, [UUID])


@pytest.mark.parametrize("total", [True, -1, 1.5, "1", {}, []])
def test_bundle_total_count_is_nonnegative_integer_when_present(total):
    with pytest.raises(ValueError, match="total_count"):
        _fetch_bundles(StaticClient([{
            "items": [], "total_count": total, "has_next": False,
        }]), [UUID])


@pytest.mark.parametrize("sku", [None, "", "   ", True, 0, -1, 1.5, {}, []])
def test_bundle_item_requires_usable_sku(sku):
    with pytest.raises(ValueError, match="SKU"):
        _normalize([{
            "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
            "bundle_id": UUID,
        }], {UUID: [{"sku": sku, "quantity": 1}]})


@pytest.mark.parametrize("sku", [7, "SKU-7"])
def test_bundle_item_accepts_positive_integer_or_nonblank_string_sku(sku):
    rows, diagnostics, quality = _normalize([{
        "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
        "bundle_id": UUID,
    }], {UUID: [{"sku": sku, "quantity": 0}]})
    assert [(row.sku, row.inbound_quantity) for row in rows] == [(str(sku), 0)]
    assert diagnostics == () and quality == OzonRecordQualityEvidence()


def test_invalid_quantity_is_scoped_to_known_sku():
    rows, diagnostics, quality = _normalize([{
        "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
        "bundle_id": UUID,
    }], {UUID: [
        {"sku": "SKU-A", "quantity": 2},
        {"sku": "SKU-B", "quantity": None},
    ]})
    assert [(row.sku, row.inbound_quantity) for row in rows] == [("SKU-A", 2)]
    assert quality == OzonRecordQualityEvidence(1, ("SKU-B",))
    assert [(item.code, item.severity) for item in diagnostics] == [
        ("INVALID_SUPPLY_BUNDLE_ITEM", "warning")]


def test_unknown_state_and_unresolved_cluster_are_sku_scoped():
    rows, diagnostics, quality = _normalize([
        {"state": "SUPPLY_TELEPORTED", "bundle_id": "future"},
        {"state": "IN_TRANSIT", "macrolocal_cluster_id": {},
         "bundle_id": "unplaced"},
    ], {
        "future": [{"sku": "SKU-B", "quantity": 1}],
        "unplaced": [{"sku": "SKU-C", "quantity": 1}],
    })
    assert rows == ()
    assert quality == OzonRecordQualityEvidence(2, ("SKU-B", "SKU-C"))
    assert {(item.code, item.severity) for item in diagnostics} == {
        ("UNKNOWN_SUPPLY_STATE", "warning"),
        ("INVALID_SUPPLY_MACROLOCAL_CLUSTER_ID", "warning"),
    }


def test_one_item_with_multiple_scoped_failures_is_rejected_once():
    rows, diagnostics, quality = _normalize([{
        "state": "SUPPLY_TELEPORTED", "macrolocal_cluster_id": 999,
        "bundle_id": UUID,
    }], {UUID: [{"sku": "SKU-B", "quantity": None}]})
    assert rows == ()
    assert quality == OzonRecordQualityEvidence(1, ("SKU-B",))
    assert {item.code for item in diagnostics} == {
        "UNKNOWN_SUPPLY_STATE", "INVALID_SUPPLY_BUNDLE_ITEM"}


@pytest.mark.parametrize("warehouse_id", ["501", True, 1.5, {}, []])
def test_wrong_type_warehouse_fallback_is_sku_scoped(warehouse_id):
    rows, diagnostics, quality = _normalize([{
        "state": "IN_TRANSIT",
        "storage_warehouse": {"warehouse_id": warehouse_id},
        "bundle_id": UUID,
    }], {UUID: [{"sku": "SKU-B", "quantity": 1}]}, mapping={501: 10})
    assert rows == ()
    assert quality == OzonRecordQualityEvidence(1, ("SKU-B",))
    assert [(item.code, item.severity) for item in diagnostics] == [
        ("UNRESOLVED_SUPPLY_CLUSTER", "warning")]
