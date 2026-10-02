from datetime import date
from fastapi.testclient import TestClient
import pytest

import backend.api as api
from backend.main import app
from backend.analytics._weeks import ObservationCoverage
from backend.economics.daily_series import build_daily_evidence
from backend.shipment.store import AnalysisSnapshotStore
from tests.economics.test_workspace import sample_snapshot
from tests.economics.test_daily_series import order
from tests.api.test_analysis import _analysis_files, _analysis_data


@pytest.fixture
def client(monkeypatch):
    snapshot=sample_snapshot()
    snapshot.snapshot_id='snap'
    snapshot.daily_order_evidence=build_daily_evidence([order('2026-09-01',100,40,2,sku='SKU')],
        ObservationCoverage(date(2026,9,1),date(2026,9,3)))
    store=AnalysisSnapshotStore();store.put(snapshot)
    monkeypatch.setattr(api,'ANALYSIS_STORE',store)
    return TestClient(app)


def test_series_is_by_sku_and_keeps_price_evidence_server_side(client):
    result=client.post('/api/economics/daily-series',json={'analysis_snapshot_id':'snap','skus':['SKU']})
    assert result.status_code==200,result.text
    series=result.json()['series']['SKU']
    assert series['period']=={'from':'2026-09-01','to':'2026-09-03'}
    assert series['days'][0]=={'day':'2026-09-01','orders':2,'spp':'0.6',
        'buyer_price_mean':'40','spp_priced_qty':2,'buyer_priced_qty':2}
    assert series['days'][1]=={'day':'2026-09-02','orders':0,'spp':None,
        'buyer_price_mean':None,'spp_priced_qty':0,'buyer_priced_qty':0}
    assert all('seller_price' not in day and 'buyer_price' not in day for day in series['days'])


@pytest.mark.parametrize('skus',[[],['26572'],[True],['SKU']*101,'SKU'])
def test_invalid_or_article_selector_is_rejected(client,skus):
    result=client.post('/api/economics/daily-series',json={'analysis_snapshot_id':'snap','skus':skus})
    assert result.status_code==400


def test_stale_or_changed_snapshot_cannot_supply_series(client,monkeypatch):
    body={'analysis_snapshot_id':'old','skus':['SKU']}
    assert client.post('/api/economics/daily-series',json=body).status_code==409
    original=api.daily_series
    def stale(*args, **kwargs):
        result=original(*args, **kwargs);api.ANALYSIS_STORE.clear();return result
    monkeypatch.setattr(api,'daily_series',stale)
    assert client.post('/api/economics/daily-series',json={**body,'analysis_snapshot_id':'snap'}).status_code==409


def test_real_file_analysis_uses_all_order_states_and_paid_total(client):
    files=_analysis_files()
    files['orders_file']=('orders.csv',('SKU;Количество;Цена продавца;Оплачено покупателем;Кластер отгрузки;Кластер доставки;Статус;Принят в обработку\n'
        'SKU-1;2;1000;800;Москва;Москва;Доставлен;2026-09-01T10:00:00\n'
        'SKU-1;1;1000;400;Москва;Москва;Отменён;2026-09-01T12:00:00\n').encode())
    analysis=client.post('/api/analysis',files=files,data=_analysis_data(as_of='2026-09-30',
        orders_period_from='2026-09-01',orders_period_to='2026-09-30'))
    assert analysis.status_code==200,analysis.text
    snapshot=analysis.json()['snapshot']
    assert 'daily_order_evidence' not in snapshot
    result=client.post('/api/economics/daily-series',json={'analysis_snapshot_id':snapshot['snapshot_id'],'skus':['SKU-1']})
    assert result.status_code==200,result.text
    day=result.json()['series']['SKU-1']['days'][0]
    assert day['orders']==3 and day['spp']=='0.6'
    assert float(day['buyer_price_mean'])==400
    assert day['spp_priced_qty']==day['buyer_priced_qty']==3


def test_background_price_evidence_updates_series_without_changing_analysis(client, monkeypatch, tmp_path):
    from threading import Event
    from types import SimpleNamespace as NS
    from backend.ozon.price_enrichment import OrderPriceEnrichment
    from backend.ozon.adapters.orders import fetch_postings
    from backend.ozon.endpoints import FBO_POSTINGS_PATH
    from tests.ozon.adapters.test_orders import fbo
    from tests.ozon.adapters.test_order_price_enrichment import Client, detail
    entered, release = Event(), Event()
    posting = fbo(); posting['products'][0]['sku'] = 'SKU'
    posting['in_process_at'] = '2026-09-01T10:00:00Z'
    requests = []
    rows, _, _ = fetch_postings(Client([posting], {}), FBO_POSTINGS_PATH,
        date(2026,9,1), date(2026,9,3), price_requests=requests)
    snapshot = api.ANALYSIS_STORE.latest()
    snapshot.source_snapshot_id = 'source'
    snapshot.daily_order_evidence = api.build_daily_evidence(rows,
        ObservationCoverage(date(2026,9,1), date(2026,9,3)))
    original = snapshot.daily_order_evidence
    service = OrderPriceEnrichment(tmp_path/'prices.json')
    monkeypatch.setattr(api, 'ORDER_PRICE_ENRICHMENT', service)
    class Slow(Client):
        def post_json(self, path, payload, **kwargs):
            entered.set(); assert release.wait(5)
            return super().post_json(path, payload, **kwargs)
    service.start(NS(source_snapshot_id='source', credential_context_id='account', orders=rows),
        requests, Slow([], {'1': detail('1', [{'product_id':'SKU', 'customer_price':40}])}),
        is_current=lambda: True)
    assert entered.wait(2)
    body = {'analysis_snapshot_id':'snap', 'skus':['SKU']}
    pending = client.post('/api/economics/daily-series', json=body)
    assert pending.status_code == 200
    assert pending.json()['series']['SKU']['price_pending']
    assert pending.json()['series']['SKU']['days'][0]['spp'] is None
    release.set(); service.wait(5)
    ready = client.post('/api/economics/daily-series', json=body).json()['series']['SKU']
    assert not ready['price_pending']
    assert ready['days'][0]['spp'] == '0.6' and ready['days'][0]['buyer_price_mean'] == '40'
    assert snapshot.daily_order_evidence is original and original.days[0].spp is None
