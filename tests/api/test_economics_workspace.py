from fastapi.testclient import TestClient

import backend.api as api
from backend.main import app
from backend.shipment.store import AnalysisSnapshotStore
from tests.economics.test_workspace import sample_snapshot
from tests.api.test_analysis import _analysis_files, _analysis_data


CLIENT = TestClient(app)
BODY = {'analysis_snapshot_id': 'snap-1', 'target_margin': '0.20',
        'target_roi': '0.40', 'goal': 'margin', 'planned_drr': '0.05'}


def test_report_is_tied_to_current_snapshot_and_has_no_mock_data(monkeypatch):
    store = AnalysisSnapshotStore()
    monkeypatch.setattr(api, 'ANALYSIS_STORE', store)
    snapshot = sample_snapshot()
    snapshot.snapshot_id = 'snap-1'
    store.put(snapshot)
    result = CLIENT.post('/api/economics/workspace', json=BODY)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload['snapshot_id'] == 'snap-1'
    assert payload['workspace']['products'][0]['article'] == '26572'
    assert payload['workspace']['modeled_shortfall'] == '130'
    assert payload['workspace']['products'][0]['applied_drr_rate'] == '0'
    assert payload['workspace']['period']['to'] == '2026-09-27'
    store.clear()
    stale = CLIENT.post('/api/economics/workspace', json=BODY)
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'ANALYSIS_SNAPSHOT_STALE'


def test_invalid_money_input_fails_closed(monkeypatch):
    store = AnalysisSnapshotStore()
    monkeypatch.setattr(api, 'ANALYSIS_STORE', store)
    snapshot = sample_snapshot()
    snapshot.snapshot_id = 'snap-1'
    store.put(snapshot)
    response = CLIENT.post('/api/economics/workspace', json={**BODY, 'planned_drr': 'NaN'})
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'INVALID_ECONOMICS_SCENARIO'


def test_completed_file_analysis_drives_workspace_without_client_math(monkeypatch):
    monkeypatch.setattr(api, 'ANALYSIS_STORE', AnalysisSnapshotStore())
    analyzed = CLIENT.post('/api/analysis', files=_analysis_files(), data=_analysis_data())
    assert analyzed.status_code == 200, analyzed.text
    snapshot = analyzed.json()['snapshot']
    assert snapshot['economics_settings']['advertising_rate'] == '0.01'
    result = CLIENT.post('/api/economics/workspace', json={
        **BODY, 'analysis_snapshot_id': snapshot['snapshot_id']})
    assert result.status_code == 200, result.text
    product = next(p for p in result.json()['workspace']['products'] if p['sku'] == 'SKU-1')
    assert product['article'] == 'ART-1'
    assert product['real_drr_rate'] is None
    assert 'order_revenue_evidence' not in snapshot
    assert 'daily_order_evidence' not in snapshot
    assert api.ANALYSIS_STORE.latest().order_revenue_evidence is not None
    assert product['groups']['destination'][0]['routes'][0]['origin'] == 'Москва'
