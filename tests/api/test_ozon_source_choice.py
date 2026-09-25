from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import backend.api as api
import pytest
from backend.project import load_project_if_exists
from backend.project import OptimizerThresholds
from backend.pack_multiplicity import pack_multiplicity_fingerprint
from backend.shipment.api_context import ShipmentPreparationError
from backend.domain.signals import SignalConfidence
from backend.ozon.adapters.local_sale import LocalSaleResult, RecommendedSupply
from backend.supply.contracts import PlacementZoneKind
from tests.api.test_analysis import CLIENT, _analysis_data, _parity_files
from tests.api.test_shipment_candidates import _analyze_api_plan


def _ready_choice(tmp_path, monkeypatch):
    monkeypatch.setattr(api, 'PROJECT_PATH', tmp_path / 'project.json')
    snapshot = _analyze_api_plan()
    stored = api.ANALYSIS_STORE.get(snapshot['snapshot_id'])
    row = stored.decision_rows[0]
    signal = LocalSaleResult((RecommendedSupply(row.sku, row.destination_cluster_id, 16),),
        datetime.now(timezone.utc).isoformat(), stored.analysis_as_of,
        stored.analysis_as_of, 56, 'EIGHT_WEEKS')
    selected = replace(row, confidence=SignalConfidence.LOW,
                       need=replace(row.need, ozon_recommended_qty=16, ozon_horizon_days=56))
    shippable = replace(stored.shippable_plan.lines[0],
                        placement_zone_kind=PlacementZoneKind.SINGLE,
                        placement_zones=('SORTABLE',))
    plan = replace(stored.shippable_plan, lines=(shippable,))
    economics = (SimpleNamespace(sku=row.sku,
        placement_cluster_id=row.destination_cluster_id, complete=True,
        profit_per_unit=Decimal('100'),margin_rate=Decimal('1'),roi=Decimal('1')),)
    api.ANALYSIS_STORE.put(replace(stored, shippable_plan=plan, decision_rows=(selected,),
                                   unit_economics=economics, ozon_recommendation=signal))
    return {'analysis_snapshot_id': snapshot['snapshot_id'],
            'shippable_plan_id': plan.shippable_plan_id,
            'sku': row.sku, 'destination_cluster_id': row.destination_cluster_id}


def test_manager_choice_changes_working_plan_and_invalidates_old_identity(tmp_path, monkeypatch):
    identity = _ready_choice(tmp_path, monkeypatch)
    base = {key: identity[key] for key in ('analysis_snapshot_id','shippable_plan_id')}
    initial = CLIENT.post('/api/working-plan', json=base).json()['working_plan']
    response = CLIENT.post('/api/working-plan/source', json={**identity, 'source':'OZON'})
    assert response.status_code == 200, response.text
    chosen = response.json()['working_plan']
    assert chosen['lines'][0]['selected_source'] == 'OZON'
    assert chosen['lines'][0]['requested_qty'] == 16
    assert chosen['lines'][0]['working_qty'] == 16
    assert initial['working_plan_id'] != chosen['working_plan_id']
    stale = CLIENT.post('/api/shipment/candidates', json={**base,
        'working_plan_id':initial['working_plan_id'],'scenario':{}})
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'WORKING_PLAN_CHANGED'
    restored = CLIENT.post('/api/working-plan/source', json={**identity,
        'source':'CALCULATED'}).json()['working_plan']
    assert restored['lines'][0]['selected_source'] == 'CALCULATED'
    assert restored['lines'][0]['working_qty'] == initial['lines'][0]['working_qty']


def test_no_api_evidence_cannot_be_selected(tmp_path, monkeypatch):
    identity = _ready_choice(tmp_path, monkeypatch)
    stored = api.ANALYSIS_STORE.get(identity['analysis_snapshot_id'])
    api.ANALYSIS_STORE.put(replace(stored, ozon_recommendation=None,
                                   ozon_recommendation_error='OZON_LOCAL_SALE_FORBIDDEN'))
    response = CLIENT.post('/api/working-plan/source', json={**identity, 'source':'OZON'})
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'OZON_RECOMMENDATION_MISSING'


def test_manager_choice_respects_thresholds_from_current_analysis(tmp_path, monkeypatch):
    identity = _ready_choice(tmp_path, monkeypatch)
    stored = api.ANALYSIS_STORE.get(identity['analysis_snapshot_id'])
    api.ANALYSIS_STORE.put(replace(stored, optimizer_thresholds=OptimizerThresholds(
        Decimal('101'), Decimal('0'), Decimal('0'))))
    response = CLIENT.post('/api/working-plan/source', json={**identity, 'source':'OZON'})
    assert response.status_code == 400, response.text
    assert response.json()['error']['code'] == 'PRODUCT_ECONOMICS_BLOCKED'


def test_bulk_selection_counts_skipped_rows_without_changing_them(tmp_path, monkeypatch):
    identity = _ready_choice(tmp_path, monkeypatch)
    response = CLIENT.post('/api/working-plan/source/bulk', json={
        'analysis_snapshot_id': identity['analysis_snapshot_id'],
        'shippable_plan_id': identity['shippable_plan_id'], 'source': 'OZON',
        'lines': [{'sku':identity['sku'], 'destination_cluster_id':identity['destination_cluster_id']},
                  {'sku':'unknown','destination_cluster_id':'Москва'}]})
    assert response.status_code == 200, response.text
    assert response.json()['selection_result']['changed'] == 1
    assert response.json()['selection_result']['skipped'] == 1
    assert response.json()['selection_result']['reasons'][0]['code'] == 'WORKING_PLAN_LINE_NOT_FOUND'


def test_manual_quantity_after_ozon_choice_switches_source_to_calculated(tmp_path, monkeypatch):
    identity = _ready_choice(tmp_path, monkeypatch)
    CLIENT.post('/api/working-plan/source', json={**identity,'source':'OZON'})
    response = CLIENT.put('/api/working-plan/override', json={**identity,'quantity':0})
    assert response.status_code == 200, response.text
    line = response.json()['working_plan']['lines'][0]
    assert line['working_qty'] == 0
    assert line['selected_source'] == 'CALCULATED'


def test_activated_new_source_invalidates_old_api_choice(tmp_path, monkeypatch):
    identity=_ready_choice(tmp_path, monkeypatch)
    CLIENT.post('/api/working-plan/source',json={**identity,'source':'OZON'})
    previous=api.OZON_SOURCE_STORE.latest()
    fresh=replace(previous,source_snapshot_id='fresh-seller-sync')
    monkeypatch.setattr(api,'OZON_SOURCE_PATH',tmp_path/'source.json')
    monkeypatch.setattr(api,'sync_ozon_source',lambda client,**kwargs:fresh)
    api._refresh_response(api.OZON_VAULT.capture_context(),'full')
    assert api.ANALYSIS_STORE.get(identity['analysis_snapshot_id']) is None
    assert identity['analysis_snapshot_id'] not in api.OZON_SOURCE_SELECTIONS
    files=_parity_files()
    response=CLIENT.post('/api/analysis',files={k:files[k] for k in
        ('tariffs_file','product_economics_file')},data=_analysis_data(
        source_mode='api',source_snapshot_id=previous.source_snapshot_id))
    assert response.status_code==409
    assert response.json()['error']['code']=='OZON_SOURCE_SNAPSHOT_STALE'


def test_analysis_commit_cannot_restore_previous_source_after_refresh(tmp_path, monkeypatch):
    identity=_ready_choice(tmp_path, monkeypatch)
    stored=api.ANALYSIS_STORE.get(identity['analysis_snapshot_id'])
    previous=api.OZON_SOURCE_STORE.latest()
    api.OZON_SOURCE_STORE.put(replace(previous,source_snapshot_id='newer-source'))
    fingerprint=pack_multiplicity_fingerprint(load_project_if_exists(api.PROJECT_PATH))
    with pytest.raises(ShipmentPreparationError) as error:
        api.commit_analysis_snapshot_if_current(stored,expected_pack_fingerprint=fingerprint)
    assert error.value.code=='OZON_SOURCE_SNAPSHOT_STALE'
