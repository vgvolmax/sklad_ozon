import pytest
from backend.domain.contracts import OrderLifecycle
from backend.ingestion.lifecycle import classify_order_lifecycle


@pytest.mark.parametrize(("raw", "expected"), [
    ("Доставлен", OrderLifecycle.FULFILLED),
    ("Доставляется", OrderLifecycle.IN_PROGRESS),
    ("Ожидает отгрузки", OrderLifecycle.IN_PROGRESS),
    ("Ожидает сборки", OrderLifecycle.IN_PROGRESS),
    ("Отменён", OrderLifecycle.CANCELLED),
])
def test_actual_ozon_statuses(raw, expected):
    assert classify_order_lifecycle(raw) == (expected, None)


def test_unknown_status_remains_unknown_with_diagnostic():
    lifecycle, diagnostic = classify_order_lifecycle("Новый статус")
    assert lifecycle is OrderLifecycle.UNKNOWN
    assert diagnostic.code == "UNKNOWN_ORDER_STATUS"
