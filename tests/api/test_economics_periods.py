from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest

import backend.api as api
from backend.main import app
from backend.shipment.store import AnalysisSnapshotStore
from tests.api.test_analysis import _analysis_files, _analysis_data
from tests.api.test_economics_workspace import BODY


@pytest.fixture
def analyzed(monkeypatch, tmp_path):
    monkeypatch.setattr(api, 'PROJECT_PATH', tmp_path / 'project.json')
    monkeypatch.setattr(api, 'ANALYSIS_STORE', AnalysisSnapshotStore())
    client = TestClient(app)
    files = _analysis_files()
    files['orders_file'] = ('orders.csv', ('SKU;Количество;Цена продавца;Цена покупателя;Кластер отгрузки;Кластер доставки;Статус;Принят в обработку\n'
        'SKU-1;2;1000;400;Москва;Москва;Доставлен;2026-09-01T10:00:00\n'
        'SKU-1;7;1000;600;Москва;Москва;Доставлен;2026-09-30T10:00:00\n').encode())
    response = client.post('/api/analysis', files=files, data=_analysis_data(
        as_of='2026-09-30', orders_period_from='2026-09-01', orders_period_to='2026-09-30'))
    assert response.status_code == 200, response.text
    snapshot = response.json()['snapshot']
    assert 'economics_period_evidence' not in snapshot
    return client, {**BODY, 'analysis_snapshot_id': snapshot['snapshot_id']}


def test_current_week_period_uses_same_quantities_in_ui_series_export(analyzed):
    client, body = analyzed
    before = api.wire(api.ANALYSIS_STORE.latest())
    body = {**body, 'period_from': '2026-09-30', 'period_to': '2026-09-30'}
    report = client.post('/api/economics/workspace', json=body)
    assert report.status_code == 200, report.text
    report = report.json()['workspace']
    assert report['products'][0]['qty'] == report['products'][0]['covered_qty'] == 7
    assert report['evidence'] == 'fulfilled_selected_period'
    series = client.post('/api/economics/daily-series', json={**body, 'skus': ['SKU-1'], 'granularity': 'week'})
    assert series.status_code == 200, series.text
    assert series.json()['series']['SKU-1']['ordered_qty'] == 7
    exported = client.post('/api/economics/export', json=body)
    assert exported.status_code == 200, exported.text
    sheet = load_workbook(BytesIO(exported.content)).active
    assert sheet['L2'].value.strftime('%Y-%m-%d') == '2026-09-30'
    assert sheet['M2'].value == sheet['L2'].value and sheet['N2'].value == 7
    assert api.wire(api.ANALYSIS_STORE.latest()) == before
    assert all(r.iso_week != 40 for r in api.ANALYSIS_STORE.latest().observed_routes.routes)


@pytest.mark.parametrize('extra', [
    {'period_from': '2026-09-01'}, {'period_from': '2026-09-30', 'period_to': '2026-09-01'},
    {'period_from': '2026-08-31', 'period_to': '2026-09-01'},
    {'period_from': '2026-09-01', 'period_to': '2026-10-01'},
    {'period_from': [], 'period_to': '2026-09-01'}])
def test_workspace_export_and_series_reject_invalid_periods(analyzed, extra):
    client, body = analyzed
    for path in ('workspace', 'export', 'daily-series'):
        response = client.post(f'/api/economics/{path}', json={**body, **extra, 'skus': ['SKU-1']})
        assert response.status_code == 400, response.text


@pytest.mark.parametrize('value', ['month', [], None])
def test_unknown_granularity_is_a_400_not_server_error(analyzed, value):
    client, body = analyzed
    response = client.post('/api/economics/daily-series', json={**body, 'skus': ['SKU-1'], 'granularity': value})
    assert response.status_code == 400
