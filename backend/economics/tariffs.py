"""Coverage-aware expected logistics over an explicitly selected route profile."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable

from backend.analytics.clean_routes import RouteDistributionCell
from backend.domain.contracts import ImportResult, TariffRow


ZERO = Decimal("0")


class RouteProfileSource(str, Enum):
    CLEAN = "clean"
    OBSERVED = "observed"
    ORIGIN_ALL_SKUS = "origin_all_skus"
    GLOBAL = "global"


class TariffLookupStatus(str, Enum):
    MATCHED = "matched"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


class LogisticsCoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NONE = "none"
    NO_PROFILE = "no_profile"


@dataclass(frozen=True, slots=True)
class LogisticsContext:
    sku: str
    origin_cluster_id: str
    volume_liters: Decimal
    price: Decimal | None
    route_profile_source: RouteProfileSource

    def __post_init__(self) -> None:
        if not isinstance(self.sku, str) or not self.sku.strip():
            raise ValueError("sku must be nonblank")
        if not isinstance(self.origin_cluster_id, str) or not self.origin_cluster_id.strip():
            raise ValueError("origin_cluster_id must be nonblank")
        _validate_nonnegative_decimal(self.volume_liters, "volume_liters")
        if self.price is not None:
            _validate_nonnegative_decimal(self.price, "price")
        if not isinstance(self.route_profile_source, RouteProfileSource):
            raise TypeError("route_profile_source must be RouteProfileSource")


@dataclass(frozen=True, slots=True)
class RouteLogisticsContribution:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    route_share: Decimal
    route_quantity: int
    route_observation_count: int
    lookup_status: TariffLookupStatus
    tariff_fee: Decimal | None
    weighted_contribution: Decimal | None
    matched_tariff_source_row: int | None


@dataclass(frozen=True, slots=True)
class LogisticsDiagnostic:
    severity: str
    code: str
    message: str
    destination_cluster_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExpectedLogisticsResult:
    sku: str
    origin_cluster_id: str
    route_profile_source: RouteProfileSource
    sample_quantity: int
    sample_observation_count: int
    profile_share_sum: Decimal
    covered_share: Decimal
    uncovered_share: Decimal
    covered_expected_fee: Decimal
    expected_fee: Decimal | None
    coverage_status: LogisticsCoverageStatus
    contributions: tuple[RouteLogisticsContribution, ...]
    tariff_source_name: str
    tariff_report_generated_at: str | None
    diagnostics: tuple[LogisticsDiagnostic, ...]


def _validate_nonnegative_decimal(value: object, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite() or value < ZERO:
        raise ValueError(f"{name} must be finite and nonnegative")


def _validate_route(route: RouteDistributionCell) -> None:
    if not isinstance(route.destination_cluster_id, str) or not route.destination_cluster_id.strip():
        raise ValueError("destination_cluster_id must be nonblank")
    if not isinstance(route.quantity, int) or isinstance(route.quantity, bool) or route.quantity <= 0:
        raise ValueError("route quantity must be a positive integer")
    if not isinstance(route.observation_count, int) or isinstance(route.observation_count, bool) or route.observation_count < 0:
        raise ValueError("route observation_count must be a nonnegative integer")
    if not isinstance(route.share, Decimal):
        raise TypeError("route share must be Decimal")
    if not route.share.is_finite() or route.share <= ZERO or route.share > Decimal("1"):
        raise ValueError("route share must be finite and in (0, 1]")


def _contains(value: Decimal, lower: Decimal | None, upper: Decimal | None) -> bool:
    return (lower is None or lower <= value) and (upper is None or value < upper)


def expected_logistics(
    profile: Iterable[RouteDistributionCell],
    tariffs: ImportResult[TariffRow],
    context: LogisticsContext,
) -> ExpectedLogisticsResult:
    """Calculate known route contributions without normalizing uncovered shares."""
    if tariffs.record_sources and len(tariffs.record_sources) != len(tariffs.records):
        raise ValueError("tariff record_sources must align with records")

    selected = tuple(
        cell for cell in profile
        if cell.sku == context.sku and cell.origin_cluster_id == context.origin_cluster_id
    )
    destinations: set[str] = set()
    for cell in selected:
        _validate_route(cell)
        if cell.destination_cluster_id in destinations:
            raise ValueError("duplicate destination in selected route profile")
        destinations.add(cell.destination_cluster_id)

    common = dict(
        sku=context.sku,
        origin_cluster_id=context.origin_cluster_id,
        route_profile_source=context.route_profile_source,
        tariff_source_name=tariffs.meta.source_name,
        tariff_report_generated_at=tariffs.meta.report_generated_at,
    )
    if not selected:
        return ExpectedLogisticsResult(
            **common,
            sample_quantity=0,
            sample_observation_count=0,
            profile_share_sum=ZERO,
            covered_share=ZERO,
            uncovered_share=ZERO,
            covered_expected_fee=ZERO,
            expected_fee=None,
            coverage_status=LogisticsCoverageStatus.NO_PROFILE,
            contributions=(),
            diagnostics=(LogisticsDiagnostic("warning", "NO_ROUTE_PROFILE", "No route profile exists for the requested SKU and origin."),),
        )

    contributions: list[RouteLogisticsContribution] = []
    diagnostics: list[LogisticsDiagnostic] = []
    covered_share = ZERO
    uncovered_share = ZERO
    covered_fee = ZERO
    for route in selected:
        volume_candidates = [
            (index, row) for index, row in enumerate(tariffs.records)
            if row.origin_cluster_id == context.origin_cluster_id
            and row.destination_cluster_id == route.destination_cluster_id
            and _contains(context.volume_liters, row.min_volume_liters, row.max_volume_liters)
        ]
        matches = [
            (index, row) for index, row in volume_candidates
            if (
                row.min_price is None and row.max_price is None
                or context.price is not None and _contains(context.price, row.min_price, row.max_price)
            )
        ]
        source_row = None
        fee = None
        weighted = None
        if len(matches) == 1:
            index, matched = matches[0]
            status = TariffLookupStatus.MATCHED
            fee = matched.logistics_fee
            weighted = route.share * fee
            source_row = tariffs.record_sources[index] if tariffs.record_sources else None
            covered_share += route.share
            covered_fee += weighted
        elif len(matches) > 1:
            status = TariffLookupStatus.AMBIGUOUS
            uncovered_share += route.share
            diagnostics.append(LogisticsDiagnostic("error", "AMBIGUOUS_TARIFF_MATCH", "More than one tariff row matches this route.", route.destination_cluster_id))
        else:
            status = TariffLookupStatus.MISSING
            uncovered_share += route.share
            price_required = context.price is None and volume_candidates and all(
                row.min_price is not None or row.max_price is not None
                for _, row in volume_candidates
            )
            diagnostics.append(LogisticsDiagnostic(
                "error",
                "PRICE_REQUIRED_FOR_TARIFF_LOOKUP" if price_required else "MISSING_TARIFF",
                "A price is required to select a tariff row." if price_required else "No tariff row matches this route.",
                route.destination_cluster_id,
            ))
        contributions.append(RouteLogisticsContribution(
            route.sku, route.origin_cluster_id, route.destination_cluster_id,
            route.share, route.quantity, route.observation_count,
            status, fee, weighted, source_row,
        ))

    matched_count = sum(item.lookup_status is TariffLookupStatus.MATCHED for item in contributions)
    if matched_count == len(contributions):
        coverage = LogisticsCoverageStatus.COMPLETE
    elif matched_count:
        coverage = LogisticsCoverageStatus.PARTIAL
    else:
        coverage = LogisticsCoverageStatus.NONE
    return ExpectedLogisticsResult(
        **common,
        sample_quantity=sum(cell.quantity for cell in selected),
        sample_observation_count=sum(cell.observation_count for cell in selected),
        profile_share_sum=sum((cell.share for cell in selected), ZERO),
        covered_share=covered_share,
        uncovered_share=uncovered_share,
        covered_expected_fee=covered_fee,
        expected_fee=covered_fee if coverage is LogisticsCoverageStatus.COMPLETE else None,
        coverage_status=coverage,
        contributions=tuple(contributions),
        diagnostics=tuple(diagnostics),
    )
