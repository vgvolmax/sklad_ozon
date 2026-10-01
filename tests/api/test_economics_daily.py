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
    assert series['days'][0]=={'day':'2026-09-01','orders':2,'spp':'0.6'}
    assert series['days'][1]=={'day':'2026-09-02','orders':0,'spp':None}
    assert 'seller_price' not in result.text and 'buyer_price' not in result.text


@pytest.mark.parametrize('skus',[[],['26572'],[True],['SKU']*101,'SKU'])
def test_invalid_or_article_selector_is_rejected(client,skus):
    result=client.post('/api/economics/daily-series',json={'analysis_snapshot_id':'snap','skus':skus})
    assert result.status_code==400


def test_stale_or_changed_snapshot_cannot_supply_series(client,monkeypatch):
    body={'analysis_snapshot_id':'old','skus':['SKU']}
    assert client.post('/api/economics/daily-series',json=body).status_code==409
    original=api.daily_series
    def stale(*args):
        result=original(*args);api.ANALYSIS_STORE.clear();return result
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
    assert result.json()['series']['SKU-1']['days'][0]=={'day':'2026-09-01','orders':3,'spp':'0.6'}
