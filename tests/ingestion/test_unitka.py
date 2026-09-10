from datetime import datetime, timezone

import backend.ingestion.unitka as unitka_module
from backend.domain.contracts import ReportMeta, SourceMode
from backend.ingestion.product_economics import import_product_economics
from backend.ingestion.tariffs import import_tariffs
from backend.supply.contracts import SupplyProductIdentity
from backend.supply.facts import build_operational_supply_facts
from tests.helpers.xlsx_fixtures import make_real_unitka

META = ReportMeta("unitka.xlsx", datetime.now(timezone.utc).isoformat())


def test_combined_unitka_matches_standalone_importers():
    data = make_real_unitka(product_rows=[["ART-1", "Товар", 100, 1000, "10%", 1]],
                            tariff_rows=[(0, "0-0,2 л", "Москва", "Казань", 18, 69)],
                            pack_rows=[["ART-1", "72/6"]])
    expected_products = import_product_economics(data, META)
    expected_tariffs = import_tariffs(data, META)
    bundle = unitka_module.import_unitka_bundle(data, META)
    assert bundle.product_economics == expected_products
    assert bundle.tariffs == expected_tariffs
    assert bundle.pack_multiplicity.records[0].pack_multiple == 6


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


def test_numeric_excel_article_joins_real_product_and_supplier_importers():
    data = make_real_unitka(
        product_rows=[[40750.0, "Товар", 100, 1000, "10%", 1]],
        pack_rows=[[40750.0, "72/6"]],
    )
    bundle = unitka_module.import_unitka_bundle(data, META)
    product = bundle.product_economics.records[0]

    facts = build_operational_supply_facts(
        products=(SupplyProductIdentity("SKU-1", product.article),),
        cluster_ids=("C",),
        pack_evidence=bundle.pack_multiplicity.records,
        source_mode=SourceMode.API,
    )

    assert product.article == "40750"
    assert facts[0].article == "40750"
    assert facts[0].pack_multiple == 6
    assert "MISSING_PACK_MULTIPLICITY" not in facts[0].reason_codes


def test_string_excel_article_is_not_fuzzily_joined_to_numeric_supplier_article():
    data = make_real_unitka(
        product_rows=[["40750.0", "Товар", 100, 1000, "10%", 1]],
        pack_rows=[[40750.0, "72/6"]],
    )
    bundle = unitka_module.import_unitka_bundle(data, META)
    product = bundle.product_economics.records[0]
    facts = build_operational_supply_facts(
        products=(SupplyProductIdentity("SKU-1", product.article),),
        cluster_ids=("C",), pack_evidence=bundle.pack_multiplicity.records,
        source_mode=SourceMode.API,
    )

    assert product.article == "40750.0"
    assert facts[0].pack_multiple is None
    assert "MISSING_PACK_MULTIPLICITY" in facts[0].reason_codes


def test_product_article_string_preserves_leading_zeroes():
    data = make_real_unitka(product_rows=[["00123", "Товар", 100, 1000, "10%", 1]])
    product = import_product_economics(data, META).records[0]
    assert product.article == "00123"
