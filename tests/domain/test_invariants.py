import pytest

from backend.domain.contracts import OrderLifecycle, OrderRecord
from backend.domain.invariants import (
    DomainValidationError, assert_non_empty, assert_non_negative, assert_rate,
    is_fulfilled_route, is_net_demand, validate_order,
)


def order(lifecycle=OrderLifecycle.FULFILLED, **changes):
    values = dict(sku="sku-1", quantity=1, lifecycle=lifecycle,
                  origin_cluster="Kazan", destination_cluster="Moscow")
    values.update(changes)
    return OrderRecord(**values)


def test_kazan_to_moscow_preserves_direction():
    record = validate_order(order())
    assert record.origin_cluster == "Kazan"
    assert record.destination_cluster == "Moscow"


@pytest.mark.parametrize("lifecycle,net,route", [
    (OrderLifecycle.FULFILLED, True, True),
    (OrderLifecycle.IN_PROGRESS, True, False),
    (OrderLifecycle.CANCELLED, False, False),
    (OrderLifecycle.UNKNOWN, False, False),
])
def test_lifecycle_populations(lifecycle, net, route):
    assert is_net_demand(order(lifecycle)) is net
    assert is_fulfilled_route(order(lifecycle)) is route


@pytest.mark.parametrize("field", ["origin_cluster", "destination_cluster"])
def test_missing_direction_is_a_serializable_validation_error(field):
    with pytest.raises(DomainValidationError) as caught:
        validate_order(order(**{field: ""}))
    assert caught.value.as_dict()["field"] == field


def test_foundation_value_guards_preserve_javascript_parity():
    assert assert_non_negative(0) == 0
    assert assert_rate(0) == 0
    assert assert_rate(1) == 1
    assert assert_non_empty("sku") == "sku"
    for call in (lambda: assert_non_negative(-1), lambda: assert_rate(1.1),
                 lambda: assert_non_empty("   ")):
        with pytest.raises(DomainValidationError):
            call()
