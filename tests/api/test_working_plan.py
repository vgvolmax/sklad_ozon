from pathlib import Path
from dataclasses import replace

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


def test_active_override_blocks_legacy_shipment_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, 'PROJECT_PATH', tmp_path / 'project.json')
    snapshot = _analyze_api_plan(); base = identity(snapshot)
    row = CLIENT.post('/api/working-plan', json=base).json()['working_plan']['lines'][0]
    CLIENT.put('/api/working-plan/override', json={**base, 'sku': row['sku'],
        'destination_cluster_id': row['destination_cluster_id'], 'quantity': 0})
    response = CLIENT.post('/api/shipment/candidates', json={**base, 'scenario': {
        'selected_cluster_ids': ['Москва'], 'date_from': '2026-09-11',
        'date_to': '2026-09-12', 'allowed_methods': ['direct'],
        'preferred_clusters_per_shipment': 1, 'max_clusters_per_shipment': 1}})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'WORKING_PLAN_REQUIRED'
