import pytest

from backend.ozon.adapters.products import fetch_product_skus
from backend.ozon.endpoints import PRODUCT_LIST_PATH


class ProductClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def post_json(self, path, payload, **_kwargs):
        self.calls.append((path, payload))
        return next(self.responses)


def page(items, total, last_id):
    return {"result": {"items": items, "total": total, "last_id": last_id}}


def test_total_reached_stops_before_nonblank_cursor():
    client = ProductClient([page([{"sku": 123}], 1, "terminal")])

    assert fetch_product_skus(client) == ("123",)
    assert len(client.calls) == 1


def test_second_page_reaches_total_without_terminal_cursor_request():
    first_items = [{"sku": value} for value in range(1, 1001)]
    second_items = [{"sku": value} for value in range(1001, 1501)]
    client = ProductClient([
        page(first_items, 1500, "page-2"),
        page(second_items, 1500, "terminal"),
    ])

    assert len(fetch_product_skus(client)) == 1500
    assert len(client.calls) == 2
    assert client.calls[1] == (
        PRODUCT_LIST_PATH,
        {"filter": {"visibility": "ALL"}, "last_id": "page-2", "limit": 1000},
    )


def test_total_not_reached_rejects_repeated_cursor():
    client = ProductClient([
        page([{"sku": 1}], 2, "same"),
        page([], 2, "same"),
    ])

    with pytest.raises(ValueError, match="non-progressing product-list"):
        fetch_product_skus(client)


@pytest.mark.parametrize("total", [None, True, -1, "100"])
def test_missing_or_invalid_total_fails_closed(total):
    result = {"items": [], "last_id": ""}
    if total is not None:
        result["total"] = total
    client = ProductClient([{"result": result}])

    with pytest.raises(ValueError, match="invalid product-list total"):
        fetch_product_skus(client)


@pytest.mark.parametrize("item", [{}, {"sku": ""}, {"sku": "   "}, {"sku": None}, "not-a-dict", {"sku": True}])
def test_invalid_sku_evidence_fails_closed(item):
    client = ProductClient([page([item], 1, "terminal")])

    with pytest.raises(ValueError, match="invalid product-list SKU evidence"):
        fetch_product_skus(client)


def test_raw_item_count_owns_completion_while_result_is_stably_deduped():
    client = ProductClient([page([{"sku": 123}, {"sku": "123"}], 2, "terminal")])

    assert fetch_product_skus(client) == ("123",)
    assert len(client.calls) == 1


def test_stable_dedupe_preserves_first_seen_order_across_pages():
    client = ProductClient([
        page([{"sku": 2}, {"sku": "2"}], 3, "next"),
        page([{"sku": " 3 "}], 3, "terminal"),
    ])

    assert fetch_product_skus(client) == ("2", "3")


@pytest.mark.parametrize("response", [
    {}, {"result": None}, {"result": {}}, {"result": {"items": None, "total": 0}},
    {"result": {"items": {}, "total": 0}},
])
def test_product_collection_envelope_is_required(response):
    with pytest.raises(ValueError):
        fetch_product_skus(ProductClient([response]))


@pytest.mark.parametrize("sku", [0, -1, 1.5, {}, [], " "])
def test_product_sku_requires_positive_integer_or_nonblank_string(sku):
    with pytest.raises(ValueError):
        fetch_product_skus(ProductClient([page([{"sku": sku}], 1, "done")]))


def test_explicit_empty_product_universe_is_valid():
    assert fetch_product_skus(ProductClient([page([], 0, "ignored")])) == ()


def test_product_total_must_remain_stable_and_may_not_be_exceeded():
    with pytest.raises(ValueError):
        fetch_product_skus(ProductClient([page([{"sku": 1}], 2, "next"), page([{"sku": 2}], 3, "done")]))
    with pytest.raises(ValueError):
        fetch_product_skus(ProductClient([page([{"sku": 1}, {"sku": 2}], 1, "done")]))


@pytest.mark.parametrize("cursor", [None, 1, {}, [], " "])
def test_product_continuation_cursor_is_strict(cursor):
    with pytest.raises(ValueError):
        fetch_product_skus(ProductClient([page([{"sku": 1}], 2, cursor)]))


def test_product_page_must_make_raw_progress():
    with pytest.raises(ValueError):
        fetch_product_skus(ProductClient([page([], 1, "next")]))


def test_identity_catalog_preserves_product_id_and_offer_without_second_request():
    from backend.ozon.adapters.products import ProductCatalogItem, fetch_product_catalog
    client = ProductClient([page([{
        "sku": 123, "product_id": 456, "offer_id": " ART-1 ",
    }], 1, "terminal")])

    assert fetch_product_catalog(client) == (ProductCatalogItem("123", 456, "ART-1"),)
    assert len(client.calls) == 1
