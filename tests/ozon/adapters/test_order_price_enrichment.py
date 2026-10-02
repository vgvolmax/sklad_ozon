"""Historical prices come from the same posting and canonical financial SKU."""

from datetime import date
import json

import pytest

from backend.ozon.adapters.orders import fetch_postings
from backend.ozon.client import OzonClient, OzonClientError
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_POSTINGS_PATH
from tests.ozon.adapters.test_orders import fbo, fbs
from tests.ozon.test_client import FakeTransport, VaultStub, response


DETAIL_PATHS = {FBO_POSTINGS_PATH: "/v2/posting/fbo/get",
                FBS_POSTINGS_PATH: "/v3/posting/fbs/get"}
START, END = date(2026, 7, 1), date(2026, 10, 1)


def detail(number, products):
    return {"result": {"posting_number": number,
                       "financial_data": {"products": products},
                       "customer": {"phone": "PRIVATE"},
                       "legal_info": {"company_name": "PRIVATE"}}}


class Client:
    def __init__(self, postings, details, *, pages=None):
        self.pages = iter(pages or [{"postings": postings, "has_next": False}])
        self.details = details
        self.calls = []

    def post_json(self, path, payload, **kwargs):
        self.calls.append((path, payload, kwargs))
        if path in DETAIL_PATHS:
            return {"result": next(self.pages)}
        result = self.details[payload["posting_number"]]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize("path,factory,sku", [
    (FBO_POSTINGS_PATH, fbo, 123), (FBS_POSTINGS_PATH, fbs, 456),
])
def test_missing_list_price_uses_verified_detail_financial_product_sku(path, factory, sku):
    posting = factory("posting-1")
    client = Client([posting], {"posting-1": detail("posting-1", [
        {"product_id": 999, "customer_price": 900},
        {"product_id": sku, "customer_price": 40, "customer_currency_code": "RUB",
         "price": 17, "payout": 11, "seller_price": 200},
    ])})

    rows, diagnostics, quality = fetch_postings(client, path, START, END)

    assert rows[0].buyer_price == 40
    assert rows[0].seller_price == (100 if sku == 123 else 55)
    assert rows[0].spp_base_price == rows[0].seller_price
    assert rows[0].source_channel == ("fbo" if sku == 123 else "fbs")
    assert diagnostics == () and quality.rejected_record_count == 0
    get = client.calls[1]
    assert get[0] == DETAIL_PATHS[path]
    assert get[1] == {"posting_number": "posting-1", "with": {"financial_data": True}}
    assert get[2]["policy"].retry_safe and get[2]["policy"].max_attempts == 3
    assert "PRIVATE" not in repr((rows, diagnostics))


def test_known_zero_price_and_explicit_malformed_prices_are_not_overwritten():
    known, invalid = fbo("known"), fbo("invalid")
    known["products"][0]["customer_price"] = 0
    invalid["products"][0]["customer_price"] = {}
    client = Client([known, invalid], {})
    rows, diagnostics, quality = fetch_postings(client, FBO_POSTINGS_PATH, START, END)
    assert [row.buyer_price for row in rows] == [0, None]
    assert len(client.calls) == 1 and quality.rejected_record_count == 0
    assert any(item.code == "ORDER_BUYER_PRICE_INVALID" for item in diagnostics)


@pytest.mark.parametrize("products", [
    [], [{"product_id": 999, "customer_price": 40}],
    [{"product_id": 123, "customer_price": 40}, {"product_id": 123, "customer_price": 20}],
    [{"product_id": 123, "price": 40, "payout": 30}],
    [{"product_id": 123, "customer_price": {"amount": 40, "currency": "USD"}}],
])
def test_detail_absence_or_invalid_identity_never_invents_price(products):
    rows, diagnostics, quality = fetch_postings(
        Client([fbo()], {"1": detail("1", products)}), FBO_POSTINGS_PATH, START, END)
    assert len(rows) == 1 and rows[0].buyer_price is None
    assert quality.rejected_record_count == 0 and quality.incomplete_skus == ()
    assert diagnostics and all(item.severity == "warning" for item in diagnostics)
    assert {item.field for item in diagnostics} == {"buyer_price"}


def test_detail_posting_identity_must_match_requested_posting():
    rows, diagnostics, _ = fetch_postings(
        Client([fbo()], {"1": detail("OTHER", [{"product_id": 123, "customer_price": 40}])}),
        FBO_POSTINGS_PATH, START, END)
    assert rows[0].buyer_price is None
    assert diagnostics[0].code == "ORDER_BUYER_PRICE_FETCH_FAILED"


def test_price_failure_preserves_demand_and_continues_enriching_next_posting():
    client = Client([fbo("1"), fbo("2")], {
        "1": OzonClientError(OzonErrorCode.UNAVAILABLE, "PRIVATE", status=503),
        "2": detail("2", [{"product_id": 123, "customer_price": 40}]),
    })
    rows, diagnostics, quality = fetch_postings(client, FBO_POSTINGS_PATH, START, END)
    assert [row.buyer_price for row in rows] == [None, 40]
    assert sum(row.quantity for row in rows) == 4
    assert quality.rejected_record_count == 0 and quality.incomplete_skus == ()
    assert all(item.severity == "warning" for item in diagnostics)
    assert "PRIVATE" not in repr(diagnostics)


def test_all_missing_postings_are_enriched_across_pages_with_progress():
    postings = [fbo(str(index)) for index in range(105)]
    client = Client([], {p["posting_number"]: detail(p["posting_number"], [
        {"product_id": 123, "customer_price": 40}]) for p in postings}, pages=[
        {"postings": postings[:100], "has_next": True, "cursor": "next"},
        {"postings": postings[100:], "has_next": False},
    ])
    events = []
    rows, diagnostics, _ = fetch_postings(
        client, FBO_POSTINGS_PATH, START, END, progress_callback=lambda **kw: events.append(kw))
    assert len(rows) == 105 and all(row.buyer_price == 40 for row in rows)
    assert len([call for call in client.calls if call[0] == DETAIL_PATHS[FBO_POSTINGS_PATH]]) == 105
    assert diagnostics == ()
    assert len([event for event in events if event.get("unit") == "postings"]) >= 105


def test_progress_cancellation_stops_before_next_detail_request():
    class Cancelled(Exception):
        pass
    client = Client([fbo("1"), fbo("2")], {
        number: detail(number, [{"product_id": 123, "customer_price": 40}])
        for number in ("1", "2")})
    def progress(**values):
        if values.get("unit") == "postings" and values["current"] == 1:
            raise Cancelled
    with pytest.raises(Cancelled):
        fetch_postings(client, FBO_POSTINGS_PATH, START, END, progress_callback=progress)
    assert len(client.calls) == 2


def test_credential_change_is_not_swallowed_as_optional_price_failure():
    client = Client([fbo()], {"1": OzonClientError(
        OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED, "changed")})
    with pytest.raises(OzonClientError) as caught:
        fetch_postings(client, FBO_POSTINGS_PATH, START, END)
    assert caught.value.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED


def test_same_posting_backfill_reuses_only_normalized_numeric_price_cache():
    cache = {}
    client = Client([], {"1": detail("1", [{"product_id": 123, "customer_price": 40}])},
                    pages=[{"postings": [fbo()], "has_next": False}] * 2)
    for _ in range(2):
        rows, diagnostics, _ = fetch_postings(client, FBO_POSTINGS_PATH, START, END, price_cache=cache)
        assert rows[0].buyer_price == 40 and diagnostics == ()
    assert len(client.calls) == 3
    assert "PRIVATE" not in repr(cache)


def test_detail_retry_and_pacing_use_existing_ozon_transport():
    payload = {"result": {"postings": [fbo()], "has_next": False}}
    transport = FakeTransport([
        response(body=json.dumps(payload).encode()), response(429, b"{}"),
        response(body=json.dumps(detail("1", [{"product_id": 123, "customer_price": 40}])).encode()),
    ])
    sleeps, clock = [], [0.0]
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    rows, diagnostics, _ = fetch_postings(
        OzonClient(VaultStub(), transport=transport, sleeper=sleep, clock=lambda: clock[0]),
        FBO_POSTINGS_PATH, START, END)
    assert rows[0].buyer_price == 40 and diagnostics == ()
    assert len(transport.calls) == 3 and sleeps


def test_finalized_known_prices_reuse_cache_on_next_refresh():
    from backend.ozon.adapters.orders import seed_order_price_cache
    first = Client([fbo()], {'1': detail('1', [{'product_id': 123, 'customer_price': 40}])})
    rows, _, _ = fetch_postings(first, FBO_POSTINGS_PATH, START, END)
    cache = seed_order_price_cache(rows)
    fresh = Client([fbo()], {})
    refreshed, _, _ = fetch_postings(fresh, FBO_POSTINGS_PATH, START, END, price_cache=cache)
    assert refreshed[0].buyer_price == 40 and len(fresh.calls) == 1
    assert '1' != refreshed[0].buyer_price_key
    assert len(refreshed[0].buyer_price_key) == 64


def test_optional_detail_permission_failure_is_not_repeated_per_posting():
    postings = [fbo(str(i)) for i in range(10)]
    client = Client(postings, {'0': OzonClientError(OzonErrorCode.PERMISSION_DENIED, 'denied', status=403)})
    rows, diagnostics, quality = fetch_postings(client, FBO_POSTINGS_PATH, START, END)
    assert len(rows) == 10 and quality.rejected_record_count == 0
    assert len(client.calls) == 2
    assert any(d.code == 'ORDER_BUYER_PRICE_FETCH_FAILED' for d in diagnostics)


def test_deferred_prices_do_not_block_usable_order_history():
    requests = []
    client = Client([fbo()], {})
    rows, _, _ = fetch_postings(client, FBO_POSTINGS_PATH, START, END, price_requests=requests)
    assert len(client.calls) == 1 and rows[0].buyer_price is None
    assert len(requests) == 1 and requests[0].key == rows[0].buyer_price_key


@pytest.mark.parametrize('invalid', [{}, {'amount': 40, 'currency': 'USD'}])
def test_duplicate_sku_never_overwrites_invalid_line(invalid):
    from copy import deepcopy
    posting = fbo()
    other = deepcopy(posting['products'][0]); other['customer_price'] = invalid
    posting['products'].append(other)
    client = Client([posting], {})
    rows, diagnostics, _ = fetch_postings(client, FBO_POSTINGS_PATH, START, END)
    assert [r.buyer_price for r in rows] == [None, None]
    assert len(client.calls) == 1
    assert diagnostics[0].code == 'ORDER_BUYER_PRICE_INVALID'
