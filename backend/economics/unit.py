"""Pure spreadsheet-parity unit economics calculations."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from backend.domain.contracts import ProductEconomicsInput
from backend.project import EconomicsSettings

from .tariffs import ExpectedLogisticsResult, LogisticsCoverageStatus


ZERO = Decimal("0")
ONE = Decimal("1")
SUPPORTED_TAX_SYSTEMS = {"usn_income", "usn_income_minus_expenses"}
KNOWN_TAX_SYSTEMS = SUPPORTED_TAX_SYSTEMS | {"osno", "manual"}


@dataclass(frozen=True, slots=True)
class RoundingMetadata:
    decimal_precision: int = 40
    decimal_rounding: str = "ROUND_HALF_EVEN"
    intermediate_quantization: bool = False
    money_quantum: Decimal | None = None
    rate_quantum: Decimal | None = None
    oracle_absolute_tolerance: Decimal = Decimal("0.0000000001")


@dataclass(frozen=True, slots=True)
class CalculationBases:
    commission_base: Decimal | None = None
    acquiring_base: Decimal | None = None
    advertising_base: Decimal | None = None
    co_invest_base: Decimal | None = None
    vat_base: Decimal | None = None
    income_tax_base: Decimal | None = None


@dataclass(frozen=True, slots=True)
class EconomicsLineItem:
    code: str
    amount: Decimal
    basis: Decimal | None = None
    rate: Decimal | None = None


@dataclass(frozen=True, slots=True)
class UnitEconomicsResult:
    sku: str
    placement_cluster_id: str
    price: Decimal | None
    commission: Decimal | None
    acquiring: Decimal | None
    base_delivery_tariff: Decimal | None
    fixed_fbo_fee: Decimal
    expected_logistics: Decimal | None
    advertising_and_services: Decimal | None
    ozon_withholdings: Decimal | None
    payout: Decimal | None
    co_invest: Decimal | None
    realization: Decimal | None
    vat: Decimal | None
    income_tax: Decimal | None
    tax: Decimal | None
    cost: Decimal | None
    profit_per_unit: Decimal | None
    margin_rate: Decimal | None
    roi: Decimal | None
    complete: bool
    blockers: tuple[str, ...]
    calculation_bases: CalculationBases
    line_items: tuple[EconomicsLineItem, ...]
    rounding: RoundingMetadata


def _decimal(value: object, name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < ZERO or positive and value == ZERO:
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return value


def _rate(value: object, name: str, *, positive: bool = False) -> Decimal:
    value = _decimal(value, name, positive=positive)
    if value > ONE:
        raise ValueError(f"{name} must be at most 1")
    return value


def calculate_unit_economics(
    product: ProductEconomicsInput,
    placement_cluster_id: str,
    logistics: ExpectedLogisticsResult,
    settings: EconomicsSettings,
) -> UnitEconomicsResult:
    """Calculate all determinable workbook line items without presentation rounding."""
    if not isinstance(product.sku, str) or not product.sku.strip():
        raise ValueError("product.sku must be nonblank")
    if not isinstance(placement_cluster_id, str) or not placement_cluster_id.strip():
        raise ValueError("placement_cluster_id must be nonblank")
    if logistics.sku != product.sku:
        raise ValueError(f"SKU mismatch: product {product.sku!r}, logistics {logistics.sku!r}")
    if logistics.origin_cluster_id != placement_cluster_id:
        raise ValueError("placement/logistics mismatch: placement must equal logistics origin")

    price = None if product.price is None else _decimal(product.price, "price")
    cost = None if product.cost is None else _decimal(product.cost, "cost")
    commission_rate = None if product.commission_rate is None else _rate(product.commission_rate, "commission_rate")
    acquiring_rate = _rate(settings.acquiring_rate, "acquiring_rate")
    advertising_rate = _rate(settings.advertising_rate, "advertising_rate")
    buyout_rate = _rate(settings.buyout_rate, "buyout_rate", positive=True)
    fixed_fbo_fee = _decimal(settings.fixed_fbo_fee, "fixed_fbo_fee")
    income_tax_rate = _rate(settings.income_tax_rate, "income_tax_rate")
    vat_rate = _rate(settings.vat_rate, "vat_rate")
    co_invest_rate = _rate(settings.co_invest_rate, "co_invest_rate")
    if settings.tax_system not in KNOWN_TAX_SYSTEMS:
        raise ValueError("tax_system must be a current persisted value")

    if not isinstance(logistics.coverage_status, LogisticsCoverageStatus):
        raise TypeError("logistics.coverage_status must be LogisticsCoverageStatus")
    logistics_complete = logistics.coverage_status is LogisticsCoverageStatus.COMPLETE
    if logistics_complete:
        if logistics.expected_fee is None:
            raise ValueError("complete logistics expected_fee must not be None")
        base_delivery_tariff = _decimal(logistics.expected_fee, "logistics.expected_fee")
    else:
        if logistics.expected_fee is not None:
            raise ValueError("incomplete logistics expected_fee must be None")
        base_delivery_tariff = None

    blockers = tuple(code for condition, code in (
        (price is None, "MISSING_PRICE"),
        (cost is None, "MISSING_COST"),
        (commission_rate is None, "MISSING_COMMISSION_RATE"),
        (not logistics_complete, "INCOMPLETE_LOGISTICS_COVERAGE"),
        (settings.tax_system not in SUPPORTED_TAX_SYSTEMS, "UNSUPPORTED_TAX_SEMANTICS"),
    ) if condition)

    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_EVEN
        commission = price * commission_rate if price is not None and commission_rate is not None else None
        acquiring = price * acquiring_rate if price is not None else None
        delivery_once = base_delivery_tariff + fixed_fbo_fee if base_delivery_tariff is not None else None
        reverse_tariff = base_delivery_tariff
        expected_logistics = (delivery_once / buyout_rate + (ONE / buyout_rate - ONE) * reverse_tariff
                              if delivery_once is not None else None)
        advertising = price * advertising_rate if price is not None else None
        withholding_parts = (commission, acquiring, expected_logistics, advertising)
        ozon_withholdings = sum(withholding_parts, ZERO) if all(value is not None for value in withholding_parts) else None
        payout = price - ozon_withholdings if price is not None and ozon_withholdings is not None else None
        co_invest = price * co_invest_rate if price is not None else None
        realization = price - co_invest if price is not None and co_invest is not None else None
        vat = (realization * vat_rate / (ONE + vat_rate) if vat_rate else ZERO) if realization is not None else None
        income_tax_base = None
        if settings.tax_system == "usn_income" and realization is not None and vat is not None:
            income_tax_base = realization - vat
        elif settings.tax_system == "usn_income_minus_expenses" and payout is not None and cost is not None and vat is not None:
            income_tax_base = payout - cost - vat
        income_tax = max(ZERO, income_tax_base * income_tax_rate) if income_tax_base is not None else None
        tax = income_tax + vat if income_tax is not None and vat is not None else None
        complete = not blockers
        profit = payout - tax - cost if complete else None
        margin = profit / price if profit is not None and price else None
        roi = profit / cost if profit is not None and cost else None

        bases = CalculationBases(
            price if commission is not None else None,
            price if acquiring is not None else None,
            price if advertising is not None else None,
            price if co_invest is not None else None,
            realization if vat is not None else None,
            income_tax_base,
        )
        candidates = (
            ("PRICE", price, None, None), ("COMMISSION", commission, price, commission_rate),
            ("ACQUIRING", acquiring, price, acquiring_rate), ("BASE_DELIVERY_TARIFF", base_delivery_tariff, None, None),
            ("FIXED_FBO_FEE", fixed_fbo_fee, None, None), ("DELIVERY_ONCE", delivery_once, base_delivery_tariff, None),
            ("REVERSE_LOGISTICS_TARIFF", reverse_tariff, base_delivery_tariff, None),
            ("EXPECTED_LOGISTICS", expected_logistics, delivery_once, buyout_rate),
            ("ADVERTISING_AND_SERVICES", advertising, price, advertising_rate),
            ("OZON_WITHHOLDINGS", ozon_withholdings, None, None), ("PAYOUT", payout, price, None),
            ("CO_INVEST", co_invest, price, co_invest_rate), ("REALIZATION", realization, price, None),
            ("VAT", vat, realization, vat_rate), ("INCOME_TAX", income_tax, income_tax_base, income_tax_rate),
            ("TOTAL_TAX", tax, None, None), ("COST", cost, None, None), ("PROFIT_PER_UNIT", profit, payout, None),
        )
        line_items = tuple(EconomicsLineItem(code, amount, basis, rate) for code, amount, basis, rate in candidates if amount is not None)

    return UnitEconomicsResult(
        product.sku, placement_cluster_id, price, commission, acquiring, base_delivery_tariff, fixed_fbo_fee,
        expected_logistics, advertising, ozon_withholdings, payout, co_invest, realization, vat, income_tax,
        tax, cost, profit, margin, roi, complete, blockers, bases, line_items, RoundingMetadata(),
    )
