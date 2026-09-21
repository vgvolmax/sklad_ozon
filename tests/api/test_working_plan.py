from pathlib import Path
from dataclasses import replace
import pytest

import backend.api as api_module
from backend.project import load_project
from tests.api.test_analysis import CLIENT
from tests.api.test_shipment_candidates import _analyze_api_plan


def identity(snapshot):
    return {'analysis_snapshot_id': snapshot['snapshot_id'],
            'shippable_plan_id': snapshot['shippable_plan']['shippable_plan_id']}


def test_working_plan_mutation_reset_and_restart_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, 'PROJECT_PATH', tmp_path / 'project.json')
    snapshot = _analyze_api_plan(); base = identity(snapshot)
    initial = CLIENT.post('/api/working-plan', json=base)
    assert initial.status_code == 200
    row = initial.json()['working_plan']['lines'][0]
    changed = CLIENT.put('/api/working-plan/override', json={**base,
        'sku': row['sku'], 'destination_cluster_id': row['destination_cluster_id'],
        'quantity': 0})
    assert changed.status_code == 200, changed.text
    assert changed.json()['working_plan']['lines'][0]['working_qty'] == 0
    assert load_project(api_module.PROJECT_PATH).working_quantity_overrides[row['sku']]
    reloaded = CLIENT.post('/api/working-plan', json=base).json()['working_plan']
    assert reloaded['lines'][0]['working_qty'] == 0
    reset = CLIENT.post('/api/working-plan/reset', json={**base,
        'sku': row['sku'], 'destination_cluster_id': row['destination_cluster_id']})
    assert reset.status_code == 200
    assert reset.json()['working_plan']['lines'][0]['is_overridden'] is False


def test_invalid_pack_quantity_is_not_persisted_and_stale_base_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, 'PROJECT_PATH', tmp_path / 'project.json')
    old = _analyze_api_plan(); base = identity(old)
    row = CLIENT.post('/api/working-plan', json=base).json()['working_plan']['lines'][0]
    invalid = CLIENT.put('/api/working-plan/override', json={**base,
        'sku': row['sku'], 'destination_cluster_id': row['destination_cluster_id'],
        'quantity': 1.5})
    assert invalid.status_code == 400
    assert not api_module.PROJECT_PATH.exists()
    stored = api_module.ANALYSIS_STORE.get(base['analysis_snapshot_id'])
    newer_plan = replace(stored.shippable_plan, analysis_snapshot_id='as_new', shippable_plan_id='sp_new')
    api_module.ANALYSIS_STORE.put(replace(stored, snapshot_id='as_new', shippable_plan=newer_plan))
    stale = CLIENT.put('/api/working-plan/override', json={**base,
        'sku': row['sku'], 'destination_cluster_id': row['destination_cluster_id'],
        'quantity': 0})
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'WORKING_PLAN_BASE_CHANGED'


def test_active_override_executes_current_working_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, 'PROJECT_PATH', tmp_path / 'project.json')
    snapshot = _analyze_api_plan(); base = identity(snapshot)
    row = CLIENT.post('/api/working-plan', json=base).json()['working_plan']['lines'][0]
    changed = CLIENT.put('/api/working-plan/override', json={**base, 'sku': row['sku'],
        'destination_cluster_id': row['destination_cluster_id'], 'quantity': 0}).json()['working_plan']
    response = CLIENT.post('/api/shipment/candidates', json={**base, 'working_plan_id': changed['working_plan_id'], 'scenario': {
        'selected_cluster_ids': ['Москва'], 'date_from': '2026-09-11',
        'date_to': '2026-09-12', 'allowed_methods': ['direct'],
        'preferred_clusters_per_shipment': 1, 'max_clusters_per_shipment': 1}})
    assert response.status_code == 200
    assert response.json()['candidates'] == []


@pytest.mark.parametrize(('path', 'method', 'payload'), [
    ('/api/working-plan/override', 'put', {'quantity': 0}),
    ('/api/working-plan/reset', 'post', {}),
    ('/api/working-plan/bulk', 'post', {'action': 'set_zero'}),
    ('/api/working-plan/reset-all', 'post', {}),
])
def test_every_mutation_rechecks_base_inside_persistence_lock(
        tmp_path, monkeypatch, path, method, payload):
    monkeypatch.setattr(api_module, 'PROJECT_PATH', tmp_path / 'project.json')
    old = _analyze_api_plan(); base = identity(old)
    row = CLIENT.post('/api/working-plan', json=base).json()['working_plan']['lines'][0]
    stored = api_module.ANALYSIS_STORE.get(base['analysis_snapshot_id'])
    newer_plan = replace(stored.shippable_plan, analysis_snapshot_id='as_race',
                         shippable_plan_id='sp_race')
    newer = replace(stored, snapshot_id='as_race', shippable_plan=newer_plan)
    original = api_module._working_base

    def advance_after_fast_precheck(*args):
        result = original(*args)
        api_module.ANALYSIS_STORE.put(newer)
        return result

    monkeypatch.setattr(api_module, '_working_base', advance_after_fast_precheck)
    request = {**base, **payload}
    if path.endswith(('override', 'reset')):
        request.update(sku=row['sku'],
                       destination_cluster_id=row['destination_cluster_id'])
    if path.endswith('bulk'):
        request['lines'] = [{'sku': row['sku'],
                             'destination_cluster_id': row['destination_cluster_id']}]
    response = getattr(CLIENT, method)(path, json=request)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'WORKING_PLAN_BASE_CHANGED'
    assert not api_module.PROJECT_PATH.exists()
