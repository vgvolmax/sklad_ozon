from decimal import Decimal
from backend.decision import (DataQualityFact, DataQualityLevel, DiagnosticView,
    build_data_quality_presentation, classify_tariff_gap)
from backend.domain.contracts import ImportResult, ReportMeta, TariffRow
from backend.domain.contracts import ProductEconomicsInput
from types import SimpleNamespace
from backend.analytics.clean_routes import RouteDistributionCell
from backend.economics import LogisticsContext, RouteProfileSource, expected_logistics


def diag(code, severity="error", sku=None, cluster=None):
    return DiagnosticView(severity, code, "message deliberately irrelevant", sku, cluster)

def fact(code, key, *, sku="SKU", origin="O", destination="D", entity="route", severity="error"):
    return DataQualityFact(code, entity, key, f"{origin} → {destination} · {sku}", severity,
                           sku=sku, origin_cluster_id=origin,
                           destination_cluster_id=destination)

def build(ds, facts=()):
    return build_data_quality_presentation(diagnostics=ds, structured_facts=facts)

def test_one_hundred_tariff_gaps_are_one_group_with_exact_entities():
    ds=[diag("MISSING_TARIFF","error",f"S{i}","O") for i in range(100)]
    facts=[fact("MISSING_TARIFF",f"S{i}::O::D",sku=f"S{i}") for i in range(100)]
    result=build(ds,facts)
    assert len(result.groups)==1
    assert (result.groups[0].primary_code,result.groups[0].affected_count,result.groups[0].raw_diagnostic_count)==("MISSING_TARIFF",100,100)

def test_duplicate_occurrences_count_raw_not_entities():
    ds=[diag("MISSING_TARIFF","error","S","O") for _ in range(5)]
    facts=[fact("MISSING_TARIFF","S::O::D") for _ in range(5)]
    group=build(ds,facts).groups[0]
    assert (group.affected_count,group.raw_diagnostic_count)==(1,5)

def test_consequence_collapses_only_with_proven_identity_and_orphan_remains():
    root=fact("MISSING_TARIFF","S::O::D")
    consequence=DataQualityFact("INCOMPLETE_LOGISTICS_COVERAGE","calculation","S::O","S · O",sku="SKU",origin_cluster_id="O")
    result=build([diag("MISSING_TARIFF","error","SKU","O"),diag("INCOMPLETE_LOGISTICS_COVERAGE","error","SKU","O")],[root,consequence])
    assert len(result.groups)==1
    assert result.groups[0].related_codes == ("MISSING_TARIFF","INCOMPLETE_LOGISTICS_COVERAGE")
    assert result.raw_diagnostic_count==2
    orphan=build([diag("INCOMPLETE_LOGISTICS_COVERAGE","error","OTHER","X")])
    assert orphan.groups[0].primary_code=="INCOMPLETE_LOGISTICS_COVERAGE"

def test_mixed_root_and_orphan_consequences_assign_each_raw_occurrence_once():
    root=fact("MISSING_TARIFF","SKU-1::O1::D",sku="SKU-1",origin="O1")
    attached=DataQualityFact("INCOMPLETE_LOGISTICS_COVERAGE","calculation","SKU-1::O1","SKU-1 · O1",sku="SKU-1",origin_cluster_id="O1")
    orphan=DataQualityFact("INCOMPLETE_LOGISTICS_COVERAGE","calculation","SKU-2::O2","SKU-2 · O2",sku="SKU-2",origin_cluster_id="O2")
    result=build([
        diag("MISSING_TARIFF","error","SKU-1","O1"),
        diag("INCOMPLETE_LOGISTICS_COVERAGE","error","SKU-1","O1"),
        diag("INCOMPLETE_LOGISTICS_COVERAGE","error","SKU-2","O2"),
    ],[root,attached,orphan])
    by={group.primary_code:group for group in result.groups}
    assert by["MISSING_TARIFF"].related_codes == (
        "MISSING_TARIFF", "INCOMPLETE_LOGISTICS_COVERAGE")
    assert by["MISSING_TARIFF"].raw_diagnostic_count == 2
    assert by["INCOMPLETE_LOGISTICS_COVERAGE"].raw_diagnostic_count == 1
    assert result.raw_diagnostic_count == 3
    assert sum(group.raw_diagnostic_count for group in result.groups) == result.raw_diagnostic_count

def test_distinct_roots_article_warning_and_repairs_stay_distinct():
    ds=[diag("MISSING_TARIFF"),diag("MISSING_PRODUCT_ECONOMICS"),diag("MISSING_SELLER_AVAILABLE_STOCK"),diag("MISSING_ARTICLE_TO_SKU","warning"),diag("WORKSHEET_DIMENSION_REPAIRED","info")]
    result=build(ds)
    assert len(result.groups)==5
    by={g.primary_code:g for g in result.groups}
    assert by["MISSING_ARTICLE_TO_SKU"].level is DataQualityLevel.WARNING and by["MISSING_ARTICLE_TO_SKU"].blocks==()
    assert by["WORKSHEET_DIMENSION_REPAIRED"].level is DataQualityLevel.TECHNICAL

def test_large_input_is_deterministic_and_bounded_by_codes():
    ds=[diag(code,"warning" if code=="MISSING_ARTICLE_TO_SKU" else "error",f"S{i%100}") for i in range(1000) for code in ("MISSING_TARIFF","MISSING_PRODUCT_ECONOMICS","MISSING_SELLER_AVAILABLE_STOCK","MISSING_ARTICLE_TO_SKU","UNKNOWN")]
    one=build(ds); two=build(reversed(ds))
    assert len(one.groups)==5
    assert sum(group.raw_diagnostic_count for group in one.groups) == one.raw_diagnostic_count
    assert [(g.primary_code,g.affected_count,g.raw_diagnostic_count) for g in one.groups]==[(g.primary_code,g.affected_count,g.raw_diagnostic_count) for g in two.groups]

def tariffs(*rows):
    return ImportResult(tuple(rows),(),ReportMeta("unitka.xlsx","now"))
def row(o="O",d="D",v0="0",v1="2",p0=None,p1=None):
    return TariffRow(o,d,Decimal(v0),Decimal(v1) if v1 else None,Decimal(p0) if p0 else None,Decimal(p1) if p1 else None,Decimal("10"))
def context(volume="1",price="100"):
    return LogisticsContext("S","O",Decimal(volume),None if price is None else Decimal(price),RouteProfileSource.CLEAN)

def test_tariff_gap_classification_pair_volume_price_required_and_ambiguous():
    assert classify_tariff_gap(tariffs(),context(),"D")=="ROUTE_PAIR_ABSENT"
    assert classify_tariff_gap(tariffs(row(v0="2",v1="3")),context(),"D")=="VOLUME_RANGE_MISSING"
    assert classify_tariff_gap(tariffs(row(p0="200",p1="300")),context(),"D")=="PRICE_RANGE_MISSING"
    assert classify_tariff_gap(tariffs(row(p0="1",p1="200")),context(price=None),"D")=="PRICE_REQUIRED"
    assert classify_tariff_gap(tariffs(row(),row()),context(),"D")=="AMBIGUOUS_MATCH"

def test_tariff_classifier_is_observational_and_preserves_canonical_money_result():
    source=tariffs(row())
    profile=(RouteDistributionCell("S","O","D",1,1,Decimal("1")),)
    before=expected_logistics(profile,source,context())
    assert classify_tariff_gap(source,context(),"D") is None
    after=expected_logistics(profile,source,context())
    assert after == before

def test_stockout_only_tariff_gaps_cover_current_and_local_routes_without_raw_counts():
    from backend.decision import build_stockout_tariff_quality_facts
    product = ProductEconomicsInput("S", "39439", Decimal("1"), 1,
        Decimal("599"), Decimal("0.1"), Decimal("1.2"))
    routes = (
        SimpleNamespace(sku="S", origin_cluster_id="Kazan",
            destination_cluster_id="Moscow",
            reason_codes=("CURRENT_ROUTE_INCOMPLETE",)),
        SimpleNamespace(sku="S", origin_cluster_id="Kazan",
            destination_cluster_id="Moscow",
            reason_codes=("LOCAL_ROUTE_INCOMPLETE",)),
    )
    impacts = (SimpleNamespace(routes=routes),)
    facts = build_stockout_tariff_quality_facts(
        stockout_episode_impacts=impacts, products=(product,), tariffs=tariffs())
    result = build((), facts)
    group = result.groups[0]
    assert group.affected_count == 2
    assert group.raw_diagnostic_count == 0
    assert {entity.label for entity in group.affected_entities} == {
        "Kazan → Moscow · S", "Moscow → Moscow · S"}

def test_stockout_and_ordinary_fact_share_exact_tariff_lookup_identity():
    from backend.decision import build_stockout_tariff_quality_facts
    product = ProductEconomicsInput("S", "39439", Decimal("1"), 1,
        Decimal("599"), Decimal("0.1"), Decimal("1.2"))
    route = SimpleNamespace(sku="S", origin_cluster_id="Kazan",
        destination_cluster_id="Moscow", reason_codes=("CURRENT_ROUTE_INCOMPLETE",))
    stockout = build_stockout_tariff_quality_facts(
        stockout_episode_impacts=(SimpleNamespace(routes=(route,)),),
        products=(product,), tariffs=tariffs())
    ordinary = DataQualityFact("MISSING_TARIFF", "route",
        "S::Kazan::Moscow::1.2::599", "Kazan → Moscow · S")
    assert build((), (ordinary,) + stockout).groups[0].affected_count == 1

def test_tariff_gap_detail_is_russian_and_keeps_machine_code_separate():
    from backend.decision import tariff_gap_user_detail
    detail = tariff_gap_user_detail("VOLUME_RANGE_MISSING", Decimal("1.2"), Decimal("599"))
    assert detail == "Нет тарифного диапазона для объёма товара · объём 1,2 л"
    assert "VOLUME_RANGE_MISSING" not in detail

def test_user_facing_decimal_formatting_preserves_integer_zeroes():
    from backend.decision.data_quality import _number
    assert [_number(Decimal(value)) for value in (
        "1000", "100", "10", "1.200", "0.50", "0.05", "0"
    )] == ["1000", "100", "10", "1,2", "0,5", "0,05", "0"]

def test_tariff_gap_detail_preserves_integer_price_and_volume_zeroes():
    from backend.decision import tariff_gap_user_detail
    assert tariff_gap_user_detail("PRICE_RANGE_MISSING", Decimal("1"), Decimal("1000")) == (
        "Нет тарифного диапазона для цены товара · цена 1000 ₽")
    assert tariff_gap_user_detail("VOLUME_RANGE_MISSING", Decimal("10"), Decimal("100")) == (
        "Нет тарифного диапазона для объёма товара · объём 10 л")

def test_product_economics_gap_classifies_absent_conflict_and_ambiguity():
    from backend.decision import classify_product_economics_gap
    raw = (ProductEconomicsInput("", "39439", None, None, None, None, None),)
    assert classify_product_economics_gap("S1", ("39439",), (), {}, {})[0] == "UNITKA_ROW_ABSENT"
    assert classify_product_economics_gap("S1", ("39439",), raw,
        {"39439": {"S1", "S2"}}, {})[0] == "ARTICLE_TO_SKU_CONFLICT"
    assert classify_product_economics_gap("S1", ("39439",), raw, {},
        {"39439": {"S1", "S2"}})[0] == "ARTICLE_TO_SKU_AMBIGUOUS"
