from datetime import date
from io import BytesIO
from zipfile import ZipFile

from backend.ingestion.recommendations import import_recommendation_xlsx
from backend.ozon.source_contracts import Cluster
from tests.helpers.xlsx_fixtures import make_xlsx


HEADERS = ['SKU', 'Артикул', 'Название товара',
           'Рекомендуемая поставка, шт на 56 дней', 'Рекомендация',
           'Кластер', 'Схема продаж']


def workbook(rows, *, malformed_dimension=False, horizon=56):
    headers = HEADERS.copy()
    headers[3] = f'Рекомендуемая поставка, шт на {horizon} дней'
    return make_xlsx(headers=[None], rows=[
        ['Период: 01.09.2026 - 28.09.2026'],
        ['Дата обновления: 29.09.2026 13:31 МСК (GMT+3)'],
        ['Фильтры: FBO, FBS'], [None], headers, *rows,
    ], malformed_dimension=malformed_dimension)


def test_exact_sku_cluster_zero_and_malformed_dimension():
    imported = import_recommendation_xlsx(workbook([
        [101.0, 'A', 'A', 0, '', 'Москва', 'FBO'],
        ['101', 'A', 'A', 7, '', ' Казань ', 'FBO, FBS'],
    ], malformed_dimension=True), 'report.xlsx', {'101'},
        (Cluster(1, 'Москва'), Cluster(2, 'Казань')))
    assert [(r.sku, r.cluster_id, r.quantity) for r in imported.records] == [
        ('101', 'Москва', 0), ('101', 'Казань', 7)]
    assert imported.meta.period_start == '2026-09-01'
    assert imported.meta.period_end == '2026-09-28'
    assert imported.meta.recommendation_horizon_days == 56
    assert imported.meta.report_generated_at == '2026-09-29T10:31:00+00:00'
    assert {d.code for d in imported.diagnostics} == {'WORKSHEET_DIMENSION_REPAIRED'}


def test_unknown_identity_fbs_only_and_duplicate_pair_are_quarantined():
    imported = import_recommendation_xlsx(workbook([
        ['101', 'A', 'A', 4, '', 'Москва', 'FBO'],
        ['101', 'A', 'A', 8, '', 'Москва', 'FBO'],
        ['101', 'A', 'A', 3, '', 'Казань', 'FBO'],
        ['101', 'A', 'A', 3, '', 'Беларусь', 'FBO'],
        ['202', 'B', 'B', 3, '', 'Казань', 'FBO'],
        ['101', 'A', 'A', 5, '', 'Казань', 'FBS'],
    ]), 'report.xlsx', {'101'}, (Cluster(1, 'Москва'), Cluster(2, 'Казань')))
    assert [(r.cluster_id, r.quantity) for r in imported.records] == [('Казань', 3)]
    assert {d.code for d in imported.diagnostics} == {
        'DUPLICATE_RECOMMENDATION', 'UNKNOWN_RECOMMENDATION_CLUSTER',
        'UNKNOWN_RECOMMENDATION_SKU', 'NON_FBO_RECOMMENDATION'}
    assert len([d for d in imported.diagnostics if d.code == 'DUPLICATE_RECOMMENDATION']) == 2


def test_wrong_schema_and_invalid_quantity_fail_closed():
    imported = import_recommendation_xlsx(workbook([
        ['101', 'A', 'A', -1, '', 'Москва', 'FBO'],
        ['101', 'A', 'A', None, '', 'Казань', 'FBO'],
    ]), 'report.xlsx', {'101'}, (Cluster(1, 'Москва'), Cluster(2, 'Казань')))
    assert imported.records == ()
    assert [d.code for d in imported.diagnostics] == [
        'INVALID_RECOMMENDATION_QUANTITY', 'INVALID_RECOMMENDATION_QUANTITY']
    assert not import_recommendation_xlsx(b'not xlsx', 'bad.xlsx', {'101'}, ()).records
    assert not import_recommendation_xlsx(b'PK corrupt', 'bad.xlsx', {'101'}, ()).records


def test_corrupt_xlsx_xml_returns_file_error():
    valid = workbook([['101', 'A', 'A', 1, '', 'Москва', 'FBO']])
    payload = BytesIO()
    with ZipFile(BytesIO(valid)) as original, ZipFile(payload, 'w') as broken:
        for name in original.namelist():
            broken.writestr(name, b'<not xml' if name == '[Content_Types].xml'
                            else original.read(name))
    result = import_recommendation_xlsx(payload.getvalue(), 'bad.xlsx', {'101'},
                                        (Cluster(1, 'Москва'),))
    assert result.records == ()
    assert result.diagnostics[0].code == 'INVALID_RECOMMENDATION_XLSX'


def test_large_excel_number_is_not_silently_rounded_into_recommendation():
    result = import_recommendation_xlsx(workbook([
        ['101', 'A', 'A', 9007199254740993, '', 'Москва', 'FBO'],
    ]), 'report.xlsx', {'101'}, (Cluster(1, 'Москва'),))
    assert result.records == ()
    assert any(d.code == 'INVALID_RECOMMENDATION_QUANTITY' for d in result.diagnostics)
