from dataclasses import replace
from decimal import Decimal

import backend.api as api
from backend.ozon.adapters.local_sale import LocalSaleResult, RecommendedSupply
from tests.api.test_analysis import CLIENT, _analysis_data, _api_parity_fixture, _parity_files


def test_old_api_recommendation_cache_is_never_reused(monkeypatch):
    source = _api_parity_fixture()
    cached = LocalSaleResult((RecommendedSupply('SKU-1', 'Москва', 12),),
        source.synced_at_utc, source.history_from, source.history_to,
        56, 'EIGHT_WEEKS')
    source = replace(source, recommended_supply=cached)
    api.OZON_SOURCE_STORE.put(source)
    monkeypatch.setattr('backend.ozon.adapters.local_sale.fetch_recommended_supply', lambda *_:
                        (_ for _ in ()).throw(AssertionError('API recommendation called')))
    files = _parity_files()
    response = CLIENT.post('/api/analysis', files={k: files[k] for k in
        ('tariffs_file', 'product_economics_file')}, data=_analysis_data(
        source_mode='api', source_snapshot_id=source.source_snapshot_id))
    assert response.status_code == 200, response.text
    snapshot = response.json()['snapshot']
    assert snapshot['decision_rows'][0]['need']['ozon_recommended_qty'] is None
    assert 'Загрузите XLSX' in snapshot['ozon_recommendation_error']


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
