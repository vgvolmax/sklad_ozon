from dataclasses import replace
from datetime import date
from threading import Event
from types import SimpleNamespace as NS

from backend.analytics._weeks import ObservationCoverage
from backend.ozon.adapters.orders import fetch_postings
from tests.ozon.adapters.test_order_price_enrichment import Client, START, END, detail
from tests.ozon.adapters.test_orders import fbo
from backend.ozon.endpoints import FBO_POSTINGS_PATH


def source():
    requests = []
    rows, _, _ = fetch_postings(Client([fbo()], {}), FBO_POSTINGS_PATH, START, END,
                                 price_requests=requests)
    return NS(source_snapshot_id='source', credential_context_id='account', orders=rows), requests


def test_background_prices_publish_immutable_evidence_without_blocking_source(tmp_path):
    from backend.ozon.price_enrichment import OrderPriceEnrichment
    from backend.economics.daily_series import build_daily_evidence
    entered, release = Event(), Event()
    src, requests = source()
    class Slow(Client):
        def post_json(self, path, payload, **kwargs):
            entered.set(); assert release.wait(5)
            return super().post_json(path, payload, **kwargs)
    client = Slow([], {'1': detail('1', [{'product_id':123, 'customer_price':40}])})
    service = OrderPriceEnrichment(tmp_path/'prices.json')
    service.start(src, requests, client, is_current=lambda: True)
    assert entered.wait(2)
    assert service.status('source')['pending']
    assert src.orders[0].buyer_price is None
    release.set(); service.wait(5)
    evidence = build_daily_evidence(src.orders, ObservationCoverage(START, END))
    updated, status = service.evidence('source', evidence)
    assert not status['pending'] and updated.days[0].buyer_price_mean == 40
    assert updated.days[0].spp is not None
    assert src.orders[0].buyer_price is None
    restored = OrderPriceEnrichment(tmp_path/'prices.json')
    assert restored.cache('account') and not restored.cache('other-account')
    restored.start(src, [], None, is_current=lambda: True)
    restored.wait(5)
    reused, _ = restored.evidence('source', evidence)
    assert reused.days[0].buyer_price_mean == 40
    text = (tmp_path/'prices.json').read_text()
    assert 'posting_number' not in text and 'PRIVATE' not in text


def test_superseded_background_result_cannot_publish_or_persist(tmp_path):
    from backend.ozon.price_enrichment import OrderPriceEnrichment
    entered, release = Event(), Event()
    src, requests = source()
    class Slow(Client):
        def post_json(self, path, payload, **kwargs):
            entered.set(); assert release.wait(5)
            return super().post_json(path, payload, **kwargs)
    service = OrderPriceEnrichment(tmp_path/'prices.json')
    service.start(src, requests, Slow([], {'1': detail('1', [{'product_id':123, 'customer_price':40}])}),
                  is_current=lambda: True)
    assert entered.wait(2)
    service.cancel()
    release.set(); service.wait(5)
    assert not service.cache('account') and not (tmp_path/'prices.json').exists()


def test_failed_price_cache_write_keeps_prices_and_no_false_success(tmp_path):
    from backend.ozon.price_enrichment import OrderPriceEnrichment
    src, requests = source()
    path = tmp_path/'directory'; path.mkdir()
    service = OrderPriceEnrichment(path)
    service.start(src, requests, Client([], {'1': detail('1', [{'product_id':123, 'customer_price':40}])}),
                  is_current=lambda: True)
    service.wait(5)
    assert service.cache('account')
    assert service.status('source')['persistence_error']


def test_credential_change_during_response_discards_price_and_file(tmp_path):
    from backend.ozon.price_enrichment import OrderPriceEnrichment
    src, requests = source()
    active = [True]
    class Changed(Client):
        def post_json(self, path, payload, **kwargs):
            result = super().post_json(path, payload, **kwargs); active[0] = False
            return result
    service = OrderPriceEnrichment(tmp_path/'prices.json')
    service.start(src, requests, Changed([], {'1': detail('1', [{'product_id':123, 'customer_price':40}])}),
                  is_current=lambda: active[0])
    service.wait(5)
    assert not service.cache('account') and not (tmp_path/'prices.json').exists()


def test_recent_pending_prices_do_not_force_full_history_next_refresh():
    from backend.ozon.sync import _order_price_version
    from backend.ozon.source_contracts import ORDER_PRICES_VERSION
    src, requests = source()
    current = date(2026,10,2)
    recent = replace(src.orders[0], accepted_at='2026-09-30T10:00:00+03:00')
    assert _order_price_version('orders_fbo', (recent,), requests, current) == ORDER_PRICES_VERSION
    assert _order_price_version('orders_fbo', src.orders, requests, current) < ORDER_PRICES_VERSION
