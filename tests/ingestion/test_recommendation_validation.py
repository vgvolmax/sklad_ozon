from datetime import date

from backend.ingestion.recommendations import import_recommendation_xlsx
from backend.ozon.source_contracts import Cluster
from tests.ingestion.test_recommendation_xlsx import workbook


def check(data, horizon=56, as_of=date(2026, 9, 29)):
    from backend.ingestion.recommendations import check_recommendation_import
    imported = import_recommendation_xlsx(data, 'report.xlsx', {'101'}, (Cluster(1, 'Москва'),))
    return check_recommendation_import(imported, horizon_days=horizon, source_as_of=as_of)


def test_preflight_distinguishes_invalid_file_from_valid_noncomparable_report():
    assert check(b'not xlsx').valid is False
    assert check(workbook([['999', 'A', 'Wrong SKU', 5, '', 'Москва', 'FBO']])).valid is False
    data = workbook([['101', 'A', 'Name', 0, '', 'Москва', 'FBO']])
    result = check(data)
    assert result.valid is True and result.usable_for_comparison is True
    for horizon, day, text in [(28, date(2026, 9, 29), 'Горизонт файла'),
                               (21, date(2026, 9, 29), 'не поддерживается'),
                               (56, date(2026, 9, 30), 'Дата отчёта')]:
        result = check(data, horizon, day)
        assert result.valid is True and result.usable_for_comparison is False
        assert text in result.message
