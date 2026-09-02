from decimal import Decimal

from backend.domain.contracts import OrderRecord, TariffRow
from backend.ingestion.availability import AvailabilityRecord
from backend.ingestion.cluster_resolution import resolve_analysis_clusters
from backend.ingestion.restrictions import RestrictionRecord, RestrictionState


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
    assert result.availability == () and result.restrictions == () and result.orders == ()
    assert [d.code for d in result.diagnostics] == ["UNRESOLVED_CLUSTER"] * 4
    assert {d.field for d in result.diagnostics} == {"cluster", "origin_cluster", "destination_cluster"}


def test_invalid_manual_target_is_reported_and_not_applied():
    result = resolve_analysis_clusters([], [], [OrderRecord("S", 1, "СПб", "Москва")],
                                       [tariff()], {"СПб": "Питер"})
    assert result.orders == ()
    assert [d.code for d in result.diagnostics] == [
        "INVALID_MANUAL_CLUSTER_TARGET", "UNRESOLVED_CLUSTER"
    ]
