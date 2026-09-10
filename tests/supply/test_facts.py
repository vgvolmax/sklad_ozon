from datetime import date
import pytest

from backend.domain.contracts import ReportMeta, SourceMode
from backend.ingestion.restrictions import RestrictionRecord, RestrictionState, import_restrictions
from backend.ingestion.supplier_packaging import PackMultiplicityEvidence
from backend.ozon.source_contracts import PlacementZoneEvidence
from backend.supply.contracts import (
    PlacementZoneKind,
    RestrictionCapacityKind,
    RestrictionEligibility,
    SupplyProductIdentity,
)
from backend.supply.facts import build_operational_supply_facts, conservative_cluster_capacity
from tests.helpers.xlsx_fixtures import make_xlsx


def restriction(sku, warehouse, state, kind, qty=None, cluster="C", zones=()):
    return RestrictionRecord(sku, warehouse, state, "", state.value, cluster, qty, kind, zones)


def test_conservative_files_capacity_is_unlimited_then_max_not_sum_then_zero():
    finite = [restriction("S", "A", RestrictionState.ALLOWED, RestrictionCapacityKind.FINITE, 20),
              restriction("S", "B", RestrictionState.ALLOWED, RestrictionCapacityKind.FINITE, 50)]
    assert conservative_cluster_capacity(finite).capacity_qty == 50
    assert conservative_cluster_capacity(finite).capacity_kind is RestrictionCapacityKind.FINITE
    unlimited = finite + [restriction("S", "C", RestrictionState.ALLOWED, RestrictionCapacityKind.UNLIMITED)]
    assert conservative_cluster_capacity(unlimited).capacity_kind is RestrictionCapacityKind.UNLIMITED
    zeros = [restriction("S", "A", RestrictionState.ALLOWED, RestrictionCapacityKind.ZERO, 0)]
    assert conservative_cluster_capacity(zeros).capacity_kind is RestrictionCapacityKind.ZERO


def test_capacity_unknown_and_prohibited_only_remain_distinct():
    unknown = [restriction("S", "A", RestrictionState.ALLOWED, RestrictionCapacityKind.UNKNOWN)]
    assert conservative_cluster_capacity(unknown).eligibility is RestrictionEligibility.ALLOWED
    assert conservative_cluster_capacity(unknown).capacity_kind is RestrictionCapacityKind.UNKNOWN
    prohibited = [restriction("S", "A", RestrictionState.PROHIBITED, RestrictionCapacityKind.UNKNOWN)]
    assert conservative_cluster_capacity(prohibited).eligibility is RestrictionEligibility.INELIGIBLE


def test_api_facts_preserve_exact_zones_join_pack_by_article_and_keep_shared_skus():
    facts = build_operational_supply_facts(
        products=(SupplyProductIdentity("123", "40750"), SupplyProductIdentity("456", "40750")),
        cluster_ids=("C",),
        pack_evidence=(PackMultiplicityEvidence("40750", 6, 2, "72/6", ()),),
        source_mode=SourceMode.API,
        placement_zone_evidence=(PlacementZoneEvidence("123", ("A", "B"), True),
                                 PlacementZoneEvidence("456", (), False)),
        restrictions=(restriction("123", "W", RestrictionState.ALLOWED, RestrictionCapacityKind.UNLIMITED),),
        restriction_report_date=date(2026, 8, 20),
    )
    assert [(f.sku, f.pack_multiple) for f in facts] == [("123", 6), ("456", 6)]
    assert facts[0].placement_zone_kind is PlacementZoneKind.MULTIPLE
    assert facts[0].placement_zones == ("A", "B")
    assert facts[1].placement_zone_kind is PlacementZoneKind.UNKNOWN
    assert all("ARTICLE_SHARED_BY_MULTIPLE_SKUS" in f.reason_codes for f in facts)
    assert all(f.capacity_kind is RestrictionCapacityKind.UNKNOWN for f in facts)
    assert all(f.restriction_report_date is None for f in facts)


def test_missing_and_conflicting_pack_never_default_to_one():
    facts = build_operational_supply_facts(
        products=(SupplyProductIdentity("S1", ""), SupplyProductIdentity("S2", "A")),
        cluster_ids=("C",),
        pack_evidence=(PackMultiplicityEvidence("A", None, None, None, ("CONFLICTING_PACK_MULTIPLICITY",)),),
        source_mode=SourceMode.API,
    )
    assert [f.pack_multiple for f in facts] == [None, None]
    assert "MISSING_SUPPLIER_ARTICLE" in facts[0].reason_codes
    assert "CONFLICTING_PACK_MULTIPLICITY" in facts[1].reason_codes


def test_direct_duplicate_pack_evidence_conflicts_instead_of_last_wins():
    facts = build_operational_supply_facts(
        products=(SupplyProductIdentity("S", "A"),), cluster_ids=("C",),
        pack_evidence=(PackMultiplicityEvidence("A", 6, 2, "72/6", ()),
                       PackMultiplicityEvidence("A", 12, 3, "24/12", ())),
        source_mode=SourceMode.API,
    )
    assert facts[0].pack_multiple is None
    assert "CONFLICTING_PACK_MULTIPLICITY" in facts[0].reason_codes


def test_operational_quantity_contracts_reject_booleans():
    from backend.supply.contracts import OperationalSupplyFact, RestrictionCapacityEvidence

    with pytest.raises(TypeError):
        RestrictionCapacityEvidence(RestrictionEligibility.ALLOWED, RestrictionCapacityKind.FINITE, True)
    with pytest.raises(TypeError):
        OperationalSupplyFact("S", "A", "C", True, PlacementZoneKind.UNKNOWN, (),
                              RestrictionEligibility.UNKNOWN, RestrictionCapacityKind.UNKNOWN,
                              None, None, ())


def test_files_facts_keep_dated_restriction_and_zone_evidence():
    facts = build_operational_supply_facts(
        products=(SupplyProductIdentity("S", "A"),), cluster_ids=("C",),
        pack_evidence=(PackMultiplicityEvidence("A", 6, 2, "72/6", ()),),
        source_mode=SourceMode.FILES,
        placement_zone_evidence=(PlacementZoneEvidence("S", ("API-ZONE",), True),),
        restrictions=(restriction("S", "W1", RestrictionState.ALLOWED, RestrictionCapacityKind.FINITE, 20, zones=("Z1",)),
                      restriction("S", "W2", RestrictionState.ALLOWED, RestrictionCapacityKind.FINITE, 50, zones=("Z2",))),
        restriction_report_date=date(2026, 8, 20),
    )
    fact = facts[0]
    assert fact.capacity_qty == 50
    assert fact.placement_zone_kind is PlacementZoneKind.MULTIPLE
    assert fact.placement_zones == ("Z1", "Z2")
    assert fact.restriction_report_date == date(2026, 8, 20)


def test_56_day_reference_value_is_not_part_of_restriction_or_supply_facts():
    def imported(reference):
        data = make_xlsx(
            headers=["SKU", "Кластер", "Склад", "Возможно ли поставить товар",
                     "Максимальный размер поставки", "Рекомендуемая поставка на 56 дней"],
            rows=[["S", "C", "W", "Да", 20, reference]],
        )
        return import_restrictions(data, ReportMeta("r.xlsx", "now", "2026-08-20"))

    low, high = imported(10), imported(9999)
    assert low.records == high.records
    common = dict(
        products=(SupplyProductIdentity("S", "A"),), cluster_ids=("C",),
        pack_evidence=(PackMultiplicityEvidence("A", 6, 2, "72/6", ()),),
        source_mode=SourceMode.FILES, restriction_report_date=date(2026, 8, 20),
    )
    assert build_operational_supply_facts(**common, restrictions=low.records) == \
        build_operational_supply_facts(**common, restrictions=high.records)


def test_supply_facts_do_not_introduce_stock_resolution_or_plan_layers():
    import backend.supply.facts as module

    names = set(vars(module))
    assert not names & {"resolve_stock_for_pack", "supplier_available_stock",
                        "operational_stock_resolver", "ShippablePlan", "ShippableLine"}
