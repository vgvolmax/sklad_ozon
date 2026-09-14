from datetime import date

from backend.analytics import ObservationCoverage
from backend.domain.contracts import ImportResult, OrderRecord, ReportMeta
from backend.ingestion.orders import scope_orders_to_coverage


def test_outside_declared_period_is_diagnostic_and_excluded():
    inside = OrderRecord("A", 10, "Москва", "Москва", accepted_at="2026-08-01")
    outside = OrderRecord("A", 999, "Москва", "Казань", accepted_at="2026-09-05")
    undated = OrderRecord("A", 5, "Москва", "Москва", accepted_at="bad-date")
    imported = ImportResult(
        (inside, outside, undated), (), ReportMeta("orders.csv", "now"), (2, 3, 4)
    )

    scoped = scope_orders_to_coverage(
        imported, ObservationCoverage(date(2026, 7, 1), date(2026, 8, 31))
    )

    assert scoped.records == (inside, undated)
    diagnostic = scoped.diagnostics[0]
    assert diagnostic.code == "ORDER_OUTSIDE_DECLARED_PERIOD"
    assert diagnostic.severity == "error"
    assert diagnostic.row == 3
