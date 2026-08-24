"""Explicit Ozon order-status classification."""

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle
from .normalization import normalize_text

_STATUS_MAP = {
    "доставлен": OrderLifecycle.FULFILLED,
    "доставляется": OrderLifecycle.IN_PROGRESS,
    "ожидает отгрузки": OrderLifecycle.IN_PROGRESS,
    "ожидает сборки": OrderLifecycle.IN_PROGRESS,
    "отменён": OrderLifecycle.CANCELLED,
    "отменен": OrderLifecycle.CANCELLED,
}


def classify_order_lifecycle(raw_status: object):
    status = normalize_text(raw_status)
    lifecycle = _STATUS_MAP.get(status.casefold())
    if lifecycle is not None:
        return lifecycle, None
    return OrderLifecycle.UNKNOWN, ImportDiagnostic(
        severity="warning", code="UNKNOWN_ORDER_STATUS",
        message=f"Unknown Ozon order status: {status!r}", field="status",
    )
