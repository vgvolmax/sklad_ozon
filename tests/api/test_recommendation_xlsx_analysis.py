from dataclasses import replace

import backend.api as api
from backend.ozon.source_contracts import Cluster, EndpointEvidence
from tests.api.test_analysis import CLIENT, _analysis_data, _api_parity_fixture, _parity_files
from tests.helpers.xlsx_fixtures import make_xlsx


def recommendation(rows, *, horizon=56, updated='25.08.2026 13:31'):
    return make_xlsx(headers=[None], rows=[
        ['Период: 01.08.2026 - 24.08.2026'],
        [f'Дата обновления: {updated} МСК (GMT+3)'],
        ['Фильтры: FBO, FBS'], [None],
        ['SKU', 'Артикул', 'Название товара',
         f'Рекомендуемая поставка, шт на {horizon} дней',
         'Рекомендация', 'Кластер', 'Схема продаж'],
        *rows,
    ])


def source():
    base = _api_parity_fixture()
    return replace(base, clusters=(Cluster(1, 'Москва'),),
                   endpoint_evidence=base.endpoint_evidence +
                   (EndpointEvidence('clusters', 'x', 1, True),))


def post(source, report, **data):
    api.OZON_SOURCE_STORE.put(source)
    files = {key: value for key, value in _parity_files().items()
             if key in ('tariffs_file', 'product_economics_file')}
    if report is not None:
        files['recommendation_file'] = ('Доступность товаров.xlsx', report)
    return CLIENT.post('/api/analysis', files=files, data=_analysis_data(
        source_mode='api', source_snapshot_id=source.source_snapshot_id, **data))


def test_xlsx_recommendation_zero_enters_plan_without_api_call(monkeypatch):
    monkeypatch.setattr('backend.ozon.adapters.local_sale.fetch_recommended_supply', lambda *_:
                        (_ for _ in ()).throw(AssertionError('API advice called')))
    result = post(source(), recommendation([
        ['SKU-1', 'ART-1', 'Product', 0, '', 'Москва', 'FBO'],
        ['SKU-1', 'ART-1', 'Product', 99, '', 'Беларусь', 'FBO'],
    ]))
    assert result.status_code == 200, result.text
    snap = result.json()['snapshot']
    assert snap['decision_rows'][0]['need']['ozon_recommended_qty'] == 0
    assert snap['decision_rows'][0]['need']['current_fbo_stock'] == 5
    assert snap['ozon_recommendation']['endpoint'] == 'xlsx:availability-report'
    assert snap['report_meta']['recommendation_file']['source_name'] == 'Доступность товаров.xlsx'
    assert any(d['code'] == 'UNKNOWN_RECOMMENDATION_CLUSTER' for d in snap['diagnostics'])
    skipped = next(d for d in snap['input_statuses']['recommendation_file']['diagnostics']
                   if d['code'] == 'UNKNOWN_RECOMMENDATION_CLUSTER')
    assert skipped['row'] == 8
    assert skipped['field'] == 'кластер'
    assert snap['input_statuses']['recommendation_file']['excluded_record_count'] == 1


def test_other_horizon_never_uses_56_day_xlsx():
    response = post(source(), recommendation([
        ['SKU-1', 'ART-1', 'Product', 3, '', 'Москва', 'FBO'],
    ]), horizon_days='28')
    assert response.status_code == 200, response.text
    snap = response.json()['snapshot']
    assert snap['decision_rows'][0]['need']['ozon_recommended_qty'] is None
    assert 'Горизонт файла' in snap['ozon_recommendation_error']


def test_unsupported_scenario_cannot_use_matching_arbitrary_xlsx_horizon():
    response = post(source(), recommendation([
        ['SKU-1', 'ART-1', 'Product', 3, '', 'Москва', 'FBO'],
    ], horizon=21), horizon_days='21')
    assert response.status_code == 200, response.text
    snap = response.json()['snapshot']
    assert snap['ozon_recommendation'] is None
    assert snap['decision_rows'][0]['need']['ozon_recommended_qty'] is None
    assert 'не поддерживается' in snap['ozon_recommendation_error']


def test_report_from_different_business_day_does_not_drive_plan():
    response = post(source(), recommendation([
        ['SKU-1', 'ART-1', 'Product', 3, '', 'Москва', 'FBO'],
    ], updated='24.08.2026 13:31'))
    assert response.status_code == 200, response.text
    snap = response.json()['snapshot']
    assert snap['ozon_recommendation'] is None
    assert snap['decision_rows'][0]['need']['ozon_recommended_qty'] is None
    assert 'Дата отчёта' in snap['ozon_recommendation_error']


def test_invalid_report_is_rejected_without_api_fallback():
    response = post(source(), b'not an Excel report')
    assert response.status_code == 422
    assert response.json()['error']['field'] == 'recommendation_file'


def test_plan_uses_card_name_when_stock_response_has_no_name():
    original = source()
    updated = replace(original, product_facts=tuple(
        replace(item, product_name='Название из карточки Ozon') for item in original.product_facts))
    response = post(updated, None)
    assert response.status_code == 200, response.text
    rows = response.json()['snapshot']['decision_rows']
    assert rows and all(row['product_name'] == 'Название из карточки Ozon' for row in rows)


def test_browser_empty_file_field_keeps_own_plan_usable():
    response = post(source(), None)
    assert response.status_code == 200, response.text
    api.OZON_SOURCE_STORE.put(source())
    files = {key: value for key, value in _parity_files().items()
             if key in ('tariffs_file', 'product_economics_file')}
    files['recommendation_file'] = ('', b'')
    response = CLIENT.post('/api/analysis', files=files, data=_analysis_data(
        source_mode='api', source_snapshot_id='parity-api'))
    assert response.status_code == 200, response.text
    assert response.json()['snapshot']['ozon_recommendation'] is None
