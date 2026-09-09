from decimal import Decimal
from datetime import date

from backend.domain.contracts import OrderRecord, TariffRow
from backend.domain.contracts import OrderLifecycle
from backend.analytics.daily import build_daily_order_facts
from backend.ingestion.availability import AvailabilityRecord
from backend.ingestion.cluster_resolution import resolve_analysis_clusters
from backend.ingestion.restrictions import RestrictionRecord, RestrictionState
from backend.ozon.adapters.orders import normalize_fbs_posting


def tariff(origin="Казань", destination="Москва"):
    return TariffRow(origin, destination, Decimal(0), None, None, None, Decimal(1))


def test_exact_manual_and_directional_resolution():
    result = resolve_analysis_clusters(
        [AvailabilityRecord("S", "W", " МОСКВА ", 1)],
        [RestrictionRecord("S", "W", RestrictionState.ALLOWED, "", "да", "Москва и МО")],
        [OrderRecord("S", 1, " казань ", "МОСКВА")], [tariff()],
        {"Москва и МО": "Москва"},
    )
    assert result.availability[0].cluster == "Москва"
    assert result.restrictions[0].cluster == "Москва"
    assert (result.orders[0].origin_cluster, result.orders[0].destination_cluster) == ("Казань", "Москва")
    assert result.diagnostics == ()


def test_unresolved_records_fail_closed_without_fuzzy_matching():
    result = resolve_analysis_clusters(
        [AvailabilityRecord("S", "W", "Москв", 1)],
        [RestrictionRecord("S", "W", RestrictionState.ALLOWED, "", "да", "СПб")],
        [OrderRecord("S", 1, "Unknown", "Москва"), OrderRecord("S", 1, "Казань", "Unknown")],
        [tariff()], {},
    )
    assert result.availability == () and result.restrictions == ()
    assert result.orders == (OrderRecord("S", 1, "", "Москва"),)
    assert [d.code for d in result.diagnostics] == [
        "UNRESOLVED_CLUSTER", "UNRESOLVED_CLUSTER",
        "UNRESOLVED_ORIGIN_CLUSTER", "UNRESOLVED_CLUSTER",
    ]
    assert {d.field for d in result.diagnostics} == {"cluster", "origin_cluster", "destination_cluster"}


def test_known_destination_with_blank_origin_keeps_demand_and_excludes_flow():
    rows, adapter_diagnostics = normalize_fbs_posting({
        "posting_number": "FBS-1",
        "status_alias": "delivered",
        "in_process_at": "2026-09-06T22:30:00Z",
        "financial_data": {"cluster_from": "", "cluster_to": "Москва"},
        "products": [{"product_id": "S", "quantity": 5}],
    })

    result = resolve_analysis_clusters([], [], rows, [tariff()], {})
    facts = build_daily_order_facts(result.orders, date(2026, 9, 7))

    assert adapter_diagnostics == ()
    assert result.orders[0].accepted_at == "2026-09-07T01:30:00+03:00"
    assert [(cell.destination_cluster_id, cell.quantity) for cell in facts.demand.cells] == [("Москва", 5)]
    assert facts.demand.cells[0].day.isocalendar()[:2] == (2026, 37)
    assert facts.fulfillment.cells == ()
    assert result.diagnostics[0].code == "UNRESOLVED_ORIGIN_CLUSTER"
    assert all(row.origin_cluster not in {"UNKNOWN", "Москва"} for row in result.orders)


def test_blank_optional_restriction_cluster_is_preserved():
    restriction = RestrictionRecord(
        "S", "W", RestrictionState.ALLOWED, "", "разрешено", ""
    )

    result = resolve_analysis_clusters([], [restriction], [], [tariff()], {})

    assert result.restrictions == (restriction,)
    assert not any(
        diagnostic.code == "UNRESOLVED_CLUSTER" and diagnostic.field == "cluster"
        for diagnostic in result.diagnostics
    )


def test_invalid_manual_target_is_reported_and_not_applied():
    result = resolve_analysis_clusters([], [], [OrderRecord("S", 1, "СПб", "Москва")],
                                       [tariff()], {"СПб": "Питер"})
    assert result.orders == (OrderRecord("S", 1, "", "Москва"),)
    assert [d.code for d in result.diagnostics] == [
        "INVALID_MANUAL_CLUSTER_TARGET", "UNRESOLVED_ORIGIN_CLUSTER"
    ]
