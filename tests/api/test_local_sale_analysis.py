from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import replace

import backend.api as api
from backend.ozon.adapters.local_sale import LocalSaleResult, RecommendedSupply
from backend.ozon.endpoints import LOCAL_SALE_ITEMS_CLUSTERS_PATH
from tests.api.test_analysis import CLIENT, _analysis_data, _api_parity_fixture, _parity_files


def test_api_analysis_uses_exact_current_recommendation_without_changing_fbo(monkeypatch):
    source = _api_parity_fixture()
    api.OZON_SOURCE_STORE.put(source)
    calls = []

    def recommendation(snapshot, horizon):
        calls.append((snapshot.source_snapshot_id, horizon))
        return LocalSaleResult((RecommendedSupply('SKU-1', 'Москва', 0),),
            datetime.now(timezone.utc).isoformat(), snapshot.history_from,
            snapshot.history_to, horizon, 'EIGHT_WEEKS', LOCAL_SALE_ITEMS_CLUSTERS_PATH), None

    monkeypatch.setattr(api, '_fetch_ozon_recommendation', recommendation)
    files = _parity_files()
    response = CLIENT.post('/api/analysis', files={k: files[k] for k in
        ('tariffs_file', 'product_economics_file')},
        data=_analysis_data(source_mode='api', source_snapshot_id=source.source_snapshot_id))
    assert response.status_code == 200, response.text
    snapshot = response.json()['snapshot']
    assert calls == [('parity-api', 56)]
    assert snapshot['ozon_recommendation']['supply_period'] == 'EIGHT_WEEKS'
    assert snapshot['decision_rows'][0]['need']['ozon_recommended_qty'] == 0
    assert snapshot['decision_rows'][0]['need']['current_fbo_stock'] == 5


def test_api_analysis_reuses_56_day_recommendation_from_the_same_source_snapshot(monkeypatch):
    source = _api_parity_fixture()
    cached = LocalSaleResult((RecommendedSupply('SKU-1', 'Москва', 0),),
        datetime.now(timezone.utc).isoformat(), source.history_from,
        source.history_to, 56, 'EIGHT_WEEKS', LOCAL_SALE_ITEMS_CLUSTERS_PATH)
    source = replace(source, recommended_supply=cached)
    api.OZON_SOURCE_STORE.put(source)
    monkeypatch.setattr(api, '_fetch_ozon_recommendation', lambda *_:
                        (_ for _ in ()).throw(AssertionError('duplicate request')))
    files = _parity_files()
    response = CLIENT.post('/api/analysis', files={k: files[k] for k in
        ('tariffs_file', 'product_economics_file')}, data=_analysis_data(
        source_mode='api', source_snapshot_id=source.source_snapshot_id))
    assert response.status_code == 200, response.text
    assert response.json()['snapshot']['decision_rows'][0]['need']['ozon_recommended_qty'] == 0


def test_unsupported_horizon_never_reuses_another_period(monkeypatch):
    source = _api_parity_fixture()
    api.OZON_SOURCE_STORE.put(source)
    monkeypatch.setattr(api, '_fetch_ozon_recommendation', lambda *_: (None, 'UNSUPPORTED_OZON_PERIOD'))
    files = _parity_files()
    response = CLIENT.post('/api/analysis', files={k: files[k] for k in
        ('tariffs_file', 'product_economics_file')}, data=_analysis_data(
        source_mode='api', source_snapshot_id=source.source_snapshot_id,
        horizon_days='21'))
    assert response.status_code == 200, response.text
    snapshot = response.json()['snapshot']
    assert snapshot['decision_rows'][0]['need']['ozon_recommended_qty'] is None
    assert snapshot['ozon_recommendation'] is None
    assert snapshot['ozon_recommendation_error'] == 'UNSUPPORTED_OZON_PERIOD'
    assert not any(item['code'] == 'MISSING_OZON_RECOMMENDATIONS' and
                   item['severity'] == 'error' for item in snapshot['diagnostics'])


def test_analysis_stores_request_economic_thresholds_for_later_source_choice():
    source = _api_parity_fixture()
    api.OZON_SOURCE_STORE.put(source)
    files = _parity_files()
    response = CLIENT.post('/api/analysis', files={k: files[k] for k in
        ('tariffs_file', 'product_economics_file')},
        data=_analysis_data(source_mode='api', source_snapshot_id=source.source_snapshot_id,
                            min_profit_per_unit='123', min_margin_rate='0.15', min_roi='0.30'))
    assert response.status_code == 200, response.text
    stored = api.ANALYSIS_STORE.get(response.json()['snapshot']['snapshot_id'])
    assert stored.optimizer_thresholds.min_profit_per_unit == Decimal('123')
    assert stored.optimizer_thresholds.min_margin_rate == Decimal('0.15')
    assert stored.optimizer_thresholds.min_roi == Decimal('0.30')
