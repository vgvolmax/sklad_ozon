from backend.application import aggregate_api_need_availability
from backend.domain.contracts import AnalysisSourceCoverage
from backend.ingestion.availability import AvailabilityRecord


def coverage(*, fbo=True, inbound=True):
    return AnalysisSourceCoverage(True, True, fbo, inbound)


def row(warehouse, fbo_quantity=None, inbound_quantity=None):
    return AvailabilityRecord(
        "SKU", warehouse, "Москва", 0, None,
        fbo_quantity=fbo_quantity, inbound_quantity=inbound_quantity)


def test_cluster_inbound_is_counted_once_for_one_two_and_three_fbo_warehouses():
    for fbo_quantities in ((10,), (5, 5), (2, 3, 5)):
        records = tuple(row(f"W{index}", quantity) for index, quantity in enumerate(fbo_quantities))
        records += (row("Москва", inbound_quantity=3),)
        assert aggregate_api_need_availability(records, coverage()) == (10, 3)


def test_complete_empty_inbound_is_zero_but_incomplete_empty_inbound_is_unknown():
    records = (row("W", 10),)
    assert aggregate_api_need_availability(records, coverage(inbound=True)) == (10, 0)
    assert aggregate_api_need_availability(records, coverage(inbound=False)) == (10, None)


def test_incomplete_empty_fbo_is_unknown_not_zero():
    assert aggregate_api_need_availability((), coverage(fbo=False)) == (None, 0)


def test_partial_rows_do_not_make_an_incomplete_endpoint_complete():
    records = (row("W", 10), row("Москва", inbound_quantity=4))
    assert aggregate_api_need_availability(records, coverage(fbo=False)) == (None, 4)
    assert aggregate_api_need_availability(records, coverage(inbound=False)) == (10, None)
