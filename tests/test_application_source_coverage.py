from decimal import Decimal

from backend.application import aggregate_api_need_availability
from backend.decision.need import calculate_need
from backend.domain.contracts import AnalysisSourceCoverage
from backend.ingestion.availability import AvailabilityRecord


def coverage(*, fbo=True, inbound=True):
    return AnalysisSourceCoverage(True, True, fbo, inbound)


def test_demand_completeness_can_be_scoped_to_sku():
    scoped = AnalysisSourceCoverage(
        True, True, True, True, demand_incomplete_skus=("SKU-B",))
    assert scoped.demand_complete is True
    assert scoped.demand_complete_for("SKU-A") is True
    assert scoped.demand_complete_for("SKU-B") is False

    globally_failed = AnalysisSourceCoverage(
        False, True, True, True, demand_incomplete_skus=("SKU-B",))
    assert globally_failed.demand_complete_for("SKU-A") is False
    assert globally_failed.demand_complete_for("SKU-B") is False


def test_inbound_completeness_can_be_scoped_to_sku():
    scoped = AnalysisSourceCoverage(
        True, True, True, True, inbound_incomplete_skus=("SKU-B",))
    assert scoped.inbound_complete_for("SKU-A") is True
    assert scoped.inbound_complete_for("SKU-B") is False

    globally_failed = AnalysisSourceCoverage(
        True, True, True, False, inbound_incomplete_skus=("SKU-B",))
    assert globally_failed.inbound_complete_for("SKU-A") is False
    assert globally_failed.inbound_complete_for("SKU-B") is False


def row(warehouse, fbo_quantity=None, inbound_quantity=None):
    return AvailabilityRecord(
        "SKU", warehouse, "Москва", 0, None,
        fbo_quantity=fbo_quantity, inbound_quantity=inbound_quantity)


def test_cluster_inbound_is_counted_once_for_one_two_and_three_fbo_warehouses():
    for fbo_quantities in ((10,), (5, 5), (2, 3, 5)):
        records = tuple(row(f"W{index}", quantity) for index, quantity in enumerate(fbo_quantities))
        records += (row("Москва", inbound_quantity=3),)
        assert aggregate_api_need_availability(records, coverage(), sku="SKU") == (10, 3)


def test_complete_empty_inbound_is_zero_but_incomplete_empty_inbound_is_unknown():
    records = (row("W", 10),)
    assert aggregate_api_need_availability(records, coverage(inbound=True), sku="SKU") == (10, 0)
    assert aggregate_api_need_availability(records, coverage(inbound=False), sku="SKU") == (10, None)


def test_incomplete_empty_fbo_is_unknown_not_zero():
    assert aggregate_api_need_availability((), coverage(fbo=False), sku="SKU") == (None, 0)


def test_partial_rows_do_not_make_an_incomplete_endpoint_complete():
    records = (row("W", 10), row("Москва", inbound_quantity=4))
    assert aggregate_api_need_availability(records, coverage(fbo=False), sku="SKU") == (None, 4)
    assert aggregate_api_need_availability(records, coverage(inbound=False), sku="SKU") == (10, None)


def test_scoped_inbound_gap_overrides_partial_numeric_observation():
    records = (row("W", 10), row("Москва", inbound_quantity=4))
    scoped = AnalysisSourceCoverage(
        True, True, True, True, inbound_incomplete_skus=("SKU-A",))
    assert aggregate_api_need_availability(records, scoped, sku="SKU-A") == (10, None)
    assert aggregate_api_need_availability(records, scoped, sku="SKU-B") == (10, 4)


def _need(sku, source_coverage):
    return calculate_need(
        sku=sku,
        destination_cluster_id="Москва",
        weekly_rate=Decimal("7"),
        horizon_days=14,
        fbo_stock=3,
        inbound_qty=1,
        include_inbound=True,
        ozon_recommended_qty=10,
        ozon_horizon_days=14,
        demand_source_complete=source_coverage.demand_complete_for(sku),
    )


def test_scoped_order_corruption_blocks_only_affected_sku_need():
    source_coverage = AnalysisSourceCoverage(
        True, True, True, True, demand_incomplete_skus=("SKU-B",))

    assert _need("SKU-A", source_coverage).calculated_need_qty == 10
    assert _need("SKU-B", source_coverage).calculated_need_qty is None


def test_global_order_corruption_blocks_need_for_every_sku():
    source_coverage = AnalysisSourceCoverage(False, True, True, True)

    for sku in ("SKU-A", "SKU-B", "SKU-C"):
        need = _need(sku, source_coverage)
        assert need.calculated_need_qty is None
        assert "INCOMPLETE_DEMAND_SOURCE" in need.blocker_codes
