from dataclasses import replace
from decimal import Decimal

import pytest

from backend.analytics.clean_routes import RouteDistributionCell
from backend.domain.contracts import ImportResult, ReportMeta, TariffRow
from backend.economics import (
    LogisticsContext,
    LogisticsCoverageStatus,
    RouteProfileSource,
    TariffLookupStatus,
    expected_logistics,
)


D = Decimal
ORIGIN = "Казань"
MOSCOW = "Москва"


def route(destination: str, share: str = "1", quantity: int = 100, *, sku: str = "SKU-1", origin: str = ORIGIN) -> RouteDistributionCell:
    return RouteDistributionCell(sku, origin, destination, quantity, 2, D(share))


def tariff(destination: str, fee: str, *, origin: str = ORIGIN, min_volume: str = "0", max_volume: str | None = None, min_price: str | None = None, max_price: str | None = None) -> TariffRow:
    return TariffRow(origin, destination, D(min_volume), D(max_volume) if max_volume else None, D(min_price) if min_price else None, D(max_price) if max_price else None, D(fee))


def tariff_result(*rows: TariffRow, sources: tuple[int, ...] = ()) -> ImportResult[TariffRow]:
    return ImportResult(tuple(rows), (), ReportMeta("tariffs.xlsx", "2026-08-24T10:00:00Z", "2026-08-20"), sources)


def context(*, volume: Decimal = D("1"), price: Decimal | None = D("500"), sku: str = "SKU-1", origin: str = ORIGIN, source: RouteProfileSource = RouteProfileSource.CLEAN) -> LogisticsContext:
    return LogisticsContext(sku, origin, volume, price, source)


def test_complete_and_partial_coverage_preserve_original_80_20_weights() -> None:
    profile = (route(MOSCOW, "0.8", 80), route(ORIGIN, "0.2", 20))
    complete = expected_logistics(profile, tariff_result(tariff(MOSCOW, "50"), tariff(ORIGIN, "100")), context())
    assert complete.coverage_status is LogisticsCoverageStatus.COMPLETE
    assert complete.covered_expected_fee == complete.expected_fee == D("60.0")
    assert [item.weighted_contribution for item in complete.contributions] == [D("40.0"), D("20.0")]

    partial = expected_logistics(profile, tariff_result(tariff(MOSCOW, "50")), context())
    assert partial.coverage_status is LogisticsCoverageStatus.PARTIAL
    assert partial.covered_expected_fee == D("40.0")
    assert partial.covered_expected_fee != D("50")
    assert partial.expected_fee is None
    assert partial.covered_share == D("0.8")
    assert partial.uncovered_share == D("0.2")
    assert partial.covered_share + partial.uncovered_share == partial.profile_share_sum
    assert partial.contributions[1].lookup_status is TariffLookupStatus.MISSING
    assert partial.contributions[1].tariff_fee is None
    assert partial.contributions[1].weighted_contribution is None
    assert [(item.code, item.destination_cluster_id) for item in partial.diagnostics] == [("MISSING_TARIFF", ORIGIN)]


def test_no_coverage_and_no_profile_are_explicit() -> None:
    none = expected_logistics((route(MOSCOW, "0.6"), route(ORIGIN, "0.4")), tariff_result(), context())
    assert none.coverage_status is LogisticsCoverageStatus.NONE
    assert none.covered_share == none.covered_expected_fee == D("0")
    assert none.uncovered_share == none.profile_share_sum == D("1.0")
    assert none.expected_fee is None
    assert [item.code for item in none.diagnostics] == ["MISSING_TARIFF", "MISSING_TARIFF"]

    empty = expected_logistics((), tariff_result(), context(source=RouteProfileSource.CLEAN))
    assert empty.coverage_status is LogisticsCoverageStatus.NO_PROFILE
    assert empty.expected_fee is None and empty.contributions == ()
    assert empty.profile_share_sum == empty.covered_share == empty.uncovered_share == empty.covered_expected_fee == D("0")
    assert empty.diagnostics[0].code == "NO_ROUTE_PROFILE"
    assert empty.route_profile_source is RouteProfileSource.CLEAN


@pytest.mark.parametrize(("volume", "fee"), [(D("0.999"), D("40")), (D("1"), D("60"))])
def test_volume_bands_are_lower_inclusive_upper_exclusive(volume: Decimal, fee: Decimal) -> None:
    tariffs = tariff_result(tariff(MOSCOW, "40", max_volume="1"), tariff(MOSCOW, "60", min_volume="1", max_volume="2"))
    assert expected_logistics((route(MOSCOW),), tariffs, context(volume=volume)).expected_fee == fee


def test_unbounded_volume_and_half_open_price_bands() -> None:
    assert expected_logistics((route(MOSCOW),), tariff_result(tariff(MOSCOW, "70", min_volume="2")), context(volume=D("5"))).expected_fee == D("70")
    bands = tariff_result(tariff(MOSCOW, "40", min_price="0", max_price="500"), tariff(MOSCOW, "60", min_price="500", max_price="1000"))
    assert expected_logistics((route(MOSCOW),), bands, context(price=D("500"))).expected_fee == D("60")


def test_price_independent_matches_none_but_required_price_is_diagnostic() -> None:
    independent = expected_logistics((route(MOSCOW),), tariff_result(tariff(MOSCOW, "50")), context(price=None))
    assert independent.expected_fee == D("50")
    required = expected_logistics((route(MOSCOW),), tariff_result(tariff(MOSCOW, "50", min_price="100", max_price="1000")), context(price=None))
    assert required.expected_fee is None
    assert [item.code for item in required.diagnostics] == ["PRICE_REQUIRED_FOR_TARIFF_LOOKUP"]


def test_ambiguous_tariff_is_uncovered_and_never_arbitrarily_resolved() -> None:
    result = expected_logistics((route(MOSCOW),), tariff_result(tariff(MOSCOW, "40"), tariff(MOSCOW, "60")), context())
    contribution = result.contributions[0]
    assert result.coverage_status is LogisticsCoverageStatus.NONE
    assert contribution.lookup_status is TariffLookupStatus.AMBIGUOUS
    assert contribution.tariff_fee is contribution.weighted_contribution is None
    assert result.diagnostics[0].code == "AMBIGUOUS_TARIFF_MATCH"


def test_tariff_direction_and_profile_sku_origin_are_isolated() -> None:
    profile = (route(MOSCOW), route(ORIGIN, sku="SKU-2"), route(ORIGIN, origin=MOSCOW))
    reverse_only = tariff_result(tariff(ORIGIN, "50", origin=MOSCOW))
    result = expected_logistics(profile, reverse_only, context())
    assert result.coverage_status is LogisticsCoverageStatus.NONE
    assert result.sample_quantity == 100
    assert len(result.contributions) == 1
    assert result.contributions[0].destination_cluster_id == MOSCOW
    assert result.contributions[0].lookup_status is TariffLookupStatus.MISSING
    assert result.diagnostics[0].code == "MISSING_TARIFF"


def test_source_row_and_metadata_are_retained_and_inputs_are_immutable() -> None:
    profile = (route(MOSCOW),)
    rows = (tariff(ORIGIN, "10"), tariff(MOSCOW, "50"))
    tariffs = tariff_result(*rows, sources=(7, 11))
    ctx = context()
    before = (profile, tariffs, ctx)
    result = expected_logistics(profile, tariffs, ctx)
    assert result.contributions[0].matched_tariff_source_row == 11
    assert result.tariff_source_name == "tariffs.xlsx"
    assert result.tariff_report_generated_at == "2026-08-20"
    assert (profile, tariffs, ctx) == before
    assert all(isinstance(value, Decimal) for value in (result.profile_share_sum, result.covered_share, result.uncovered_share, result.covered_expected_fee, result.expected_fee))


def test_misaligned_source_rows_are_rejected() -> None:
    with pytest.raises(ValueError, match="record_sources"):
        expected_logistics((route(MOSCOW),), tariff_result(tariff(MOSCOW, "50"), tariff(ORIGIN, "50"), sources=(7,)), context())


@pytest.mark.parametrize("changes", [{"sku": " "}, {"origin_cluster_id": ""}, {"volume_liters": D("NaN")}, {"volume_liters": D("-1")}, {"price": D("Infinity")}, {"price": D("-1")}, {"volume_liters": 1.0}, {"price": 500.0}])
def test_context_rejects_invalid_or_non_decimal_values(changes: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(context(), **changes)


@pytest.mark.parametrize("bad_route", [route(" "), route(MOSCOW, quantity=0), replace(route(MOSCOW), observation_count=-1), replace(route(MOSCOW), share=D("0")), replace(route(MOSCOW), share=D("1.1")), replace(route(MOSCOW), share=D("NaN")), replace(route(MOSCOW), share=0.5)])
def test_selected_profile_cells_are_validated(bad_route: RouteDistributionCell) -> None:
    with pytest.raises((TypeError, ValueError)):
        expected_logistics((bad_route,), tariff_result(), context())


def test_duplicate_selected_destination_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate destination"):
        expected_logistics((route(MOSCOW, "0.5"), route(MOSCOW, "0.5")), tariff_result(), context())
