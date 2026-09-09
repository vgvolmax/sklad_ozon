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
    first_items = [{"sku": value} for value in range(1000)]
    second_items = [{"sku": value} for value in range(1000, 1500)]
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

    with pytest.raises(ValueError, match="non-progressing product-list cursor"):
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
