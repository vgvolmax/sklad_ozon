from datetime import datetime, timezone

import backend.ingestion.unitka as unitka_module
from backend.domain.contracts import ReportMeta
from backend.ingestion.product_economics import import_product_economics
from backend.ingestion.tariffs import import_tariffs
from tests.helpers.xlsx_fixtures import make_real_unitka

META = ReportMeta("unitka.xlsx", datetime.now(timezone.utc).isoformat())


def test_combined_unitka_matches_standalone_importers():
    data = make_real_unitka(product_rows=[["ART-1", "Товар", 100, 1000, "10%", 1]],
                            tariff_rows=[(0, "0-0,2 л", "Москва", "Казань", 18, 69)])
    expected_products = import_product_economics(data, META)
    expected_tariffs = import_tariffs(data, META)
    bundle = unitka_module.import_unitka_bundle(data, META)
    assert bundle.product_economics == expected_products
    assert bundle.tariffs == expected_tariffs


def test_combined_unitka_opens_workbook_once(monkeypatch):
    data = make_real_unitka()
    opens = 0
    original = unitka_module.load_workbook
    def counted(*args, **kwargs):
        nonlocal opens
        opens += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(unitka_module, "load_workbook", counted)
    unitka_module.import_unitka_bundle(data, META)
    assert opens == 1
