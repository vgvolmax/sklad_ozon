"""Pure validation and lifecycle population predicates."""

from dataclasses import dataclass
from math import isfinite
from typing import Any

from .contracts import OrderLifecycle, OrderRecord


@dataclass(frozen=True, slots=True)
class DomainValidationError(ValueError):
    code: str
    message: str
    field: str | None = None

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "field": self.field}


def assert_non_negative(value: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or value < 0):
        raise DomainValidationError("NON_NEGATIVE_REQUIRED", "value must be non-negative")
    return value


def assert_rate(value: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or not 0 <= value <= 1):
        raise DomainValidationError("RATE_OUT_OF_RANGE", "rate must be between zero and one")
    return value


def assert_non_empty(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError("NON_EMPTY_REQUIRED", "value must not be empty")
    return value


def validate_order(order: OrderRecord) -> OrderRecord:
    if not isinstance(order.origin_cluster, str):
        raise DomainValidationError(
            "INVALID_TYPE", "origin_cluster must be a string", "origin_cluster",
        )
    if not isinstance(order.destination_cluster, str) or not order.destination_cluster.strip():
        raise DomainValidationError(
            "NON_EMPTY_REQUIRED", "destination_cluster must not be empty", "destination_cluster",
        )
    if not order.sku.strip():
        raise DomainValidationError("NON_EMPTY_REQUIRED", "sku must not be empty", "sku")
    if isinstance(order.quantity, bool) or not isinstance(order.quantity, int) or order.quantity < 0:
        raise DomainValidationError(
            "NON_NEGATIVE_REQUIRED", "quantity must be a non-negative integer", "quantity",
        )
    return order


def is_net_demand(order: OrderRecord) -> bool:
    return order.lifecycle in {OrderLifecycle.FULFILLED, OrderLifecycle.IN_PROGRESS}


def is_fulfilled_route(order: OrderRecord) -> bool:
    return order.lifecycle is OrderLifecycle.FULFILLED and bool(order.origin_cluster.strip())
