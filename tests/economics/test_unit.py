import json
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from backend.domain.contracts import ProductEconomicsInput
from backend.economics import (
    ExpectedLogisticsResult,
    LogisticsCoverageStatus,
    RouteProfileSource,
    calculate_unit_economics,
)
from backend.project import EconomicsSettings


D = Decimal
ORACLE = json.loads(
    (Path(__file__).parents[1] / "fixtures/economics/spreadsheet_cases.json").read_text("utf-8")
)


def inputs(values, *, status=LogisticsCoverageStatus.COMPLETE, covered=None):
    product = ProductEconomicsInput("SKU-1", "A-1", D(values["cost"]) if values.get("cost") is not None else None,
                                    1, D(values["price"]) if values.get("price") is not None else None,
                                    D(values["commission_rate"]) if values.get("commission_rate") is not None else None, D("1"))
    settings = EconomicsSettings(*(D(values[name]) for name in ("acquiring_rate", "advertising_rate", "buyout_rate", "fixed_fbo_fee")),
                                 values["tax_system"], *(D(values[name]) for name in ("income_tax_rate", "vat_rate", "co_invest_rate")))
    fee = D(values["base_delivery_tariff"])
    logistics = ExpectedLogisticsResult("SKU-1", "Москва", RouteProfileSource.CLEAN, 1, 1, D("1"), D("1"), D("0"),
                                        fee if covered is None else D(covered), fee if status is LogisticsCoverageStatus.COMPLETE else None,
                                        status, (), "fixture", None, ())
    return product, logistics, settings


def calculate(case):
    product, logistics, settings = inputs(case["input"])
    return calculate_unit_economics(product, "Москва", logistics, settings)


@pytest.mark.parametrize("case", ORACLE["real_cached_cases"], ids=lambda c: c["id"])
def test_all_real_spreadsheet_cases(case):
    result = calculate(case)
    tolerance = D(case["comparison"]["cached_absolute_tolerance"])
    for name, expected in case["cached"].items():
        assert abs(getattr(result, name) - D(expected)) <= tolerance
    for name, expected in case["decimal_expected"].items():
        actual = getattr(result.calculation_bases, name, None) if name.endswith("_base") else getattr(result, name, None)
        if actual is None:
            actual = next(item.amount for item in result.line_items if item.code == name.upper())
        assert abs(actual - D(expected)) <= tolerance


@pytest.mark.parametrize("case", ORACLE["formula_derived_cases"], ids=lambda c: c["id"])
def test_all_formula_derived_cases(case):
    result = calculate(case)
    tolerance = D(case["comparison"]["absolute_tolerance"])
    for name, expected in case["expected"].items():
        actual = getattr(result.calculation_bases, name, None) if name.endswith("_base") else getattr(result, name, None)
        if actual is None and name not in {"margin_rate", "roi"}:
            actual = next(item.amount for item in result.line_items if item.code == name.upper())
        assert actual is None if expected is None else abs(actual - D(expected)) <= tolerance
    assert result.complete


@pytest.mark.parametrize("contract", ORACLE["contract_cases"], ids=lambda c: c["id"])
def test_all_contract_cases_block_profit_and_ignore_covered_fee(contract):
    values = ORACLE["real_cached_cases"][0]["input"]
    status = LogisticsCoverageStatus(contract["logistics"]["coverage_status"])
    product, logistics, settings = inputs(values, status=status, covered=contract["logistics"]["covered_expected_fee"])
    result = calculate_unit_economics(product, "Москва", logistics, settings)
    expected = contract["expected"]
    assert result.complete is expected["complete"]
    assert result.blockers == tuple(expected["blockers"])
    for name in ("expected_logistics", "profit_per_unit", "margin_rate", "roi"):
        assert getattr(result, name) is expected[name]
    covered = D(contract["logistics"]["covered_expected_fee"])
    assert all(item.amount != covered for item in result.line_items)


def test_auditable_row_10_and_rounding_contract():
    result = calculate(ORACLE["real_cached_cases"][0])
    assert tuple(item.code for item in result.line_items) == (
        "PRICE", "COMMISSION", "ACQUIRING", "BASE_DELIVERY_TARIFF", "FIXED_FBO_FEE", "DELIVERY_ONCE",
        "REVERSE_LOGISTICS_TARIFF", "EXPECTED_LOGISTICS", "ADVERTISING_AND_SERVICES", "OZON_WITHHOLDINGS",
        "PAYOUT", "CO_INVEST", "REALIZATION", "VAT", "INCOME_TAX", "TOTAL_TAX", "COST", "PROFIT_PER_UNIT")
    assert result.calculation_bases == result.calculation_bases.__class__(*(D("299") for _ in range(6)))
    with localcontext() as context:
        context.prec = 40
        assert result.commission + result.acquiring + result.expected_logistics + result.advertising_and_services == result.ozon_withholdings
        assert result.price - result.ozon_withholdings == result.payout
        assert result.payout - result.tax - result.cost == result.profit_per_unit
    assert (result.rounding.decimal_precision, result.rounding.decimal_rounding,
            result.rounding.intermediate_quantization, result.rounding.oracle_absolute_tolerance) == (40, "ROUND_HALF_EVEN", False, D("0.0000000001"))


@pytest.mark.parametrize("tax_system", ["osno", "manual"])
def test_unsupported_tax_semantics(tax_system):
    case = ORACLE["real_cached_cases"][0]
    product, logistics, settings = inputs({**case["input"], "tax_system": tax_system})
    result = calculate_unit_economics(product, "Москва", logistics, settings)
    assert result.blockers == ("UNSUPPORTED_TAX_SEMANTICS",)
    assert result.profit_per_unit is result.margin_rate is result.roi is None


def test_missing_values_and_blocker_order():
    values = ORACLE["real_cached_cases"][0]["input"]
    product, logistics, settings = inputs(values, status=LogisticsCoverageStatus.PARTIAL)
    product = replace(product, price=None, cost=None, commission_rate=None)
    result = calculate_unit_economics(product, "Москва", logistics, settings)
    assert result.blockers == ("MISSING_PRICE", "MISSING_COST", "MISSING_COMMISSION_RATE", "INCOMPLETE_LOGISTICS_COVERAGE")
    assert result.profit_per_unit is None


def test_zero_cost_is_complete_with_undefined_roi():
    case = ORACLE["real_cached_cases"][0]
    product, logistics, settings = inputs({**case["input"], "cost": "0"})
    result = calculate_unit_economics(product, "Москва", logistics, settings)
    assert result.complete and result.profit_per_unit is not None and result.margin_rate is not None and result.roi is None


def test_identity_mismatches_raise():
    product, logistics, settings = inputs(ORACLE["real_cached_cases"][0]["input"])
    with pytest.raises(ValueError, match="SKU mismatch"):
        calculate_unit_economics(product, "Москва", replace(logistics, sku="SKU-2"), settings)
    with pytest.raises(ValueError, match="placement/logistics mismatch"):
        calculate_unit_economics(product, "Казань", logistics, settings)


@pytest.mark.parametrize("field,value", [("price", 1.0), ("cost", D("NaN")), ("commission_rate", D("1.1")), ("price", D("-1"))])
def test_invalid_product_numbers_raise(field, value):
    product, logistics, settings = inputs(ORACLE["real_cached_cases"][0]["input"])
    with pytest.raises((TypeError, ValueError)):
        calculate_unit_economics(replace(product, **{field: value}), "Москва", logistics, settings)


@pytest.mark.parametrize("field,value", [("acquiring_rate", 0.1), ("vat_rate", D("Infinity")), ("buyout_rate", D("0")),
                                           ("fixed_fbo_fee", D("-1")), ("co_invest_rate", D("1.1"))])
def test_invalid_settings_raise(field, value):
    product, logistics, settings = inputs(ORACLE["real_cached_cases"][0]["input"])
    with pytest.raises((TypeError, ValueError)):
        calculate_unit_economics(product, "Москва", logistics, replace(settings, **{field: value}))


def test_complete_logistics_invariant_and_input_immutability():
    product, logistics, settings = inputs(ORACLE["real_cached_cases"][0]["input"])
    originals = product, logistics, settings
    calculate_unit_economics(product, "Москва", logistics, settings)
    assert (product, logistics, settings) == originals
    with pytest.raises(ValueError, match="expected_fee"):
        calculate_unit_economics(product, "Москва", replace(logistics, expected_fee=None), settings)
    with pytest.raises(ValueError, match="expected_fee"):
        calculate_unit_economics(product, "Москва", replace(logistics, coverage_status=LogisticsCoverageStatus.PARTIAL), settings)
    with pytest.raises(TypeError, match="coverage_status"):
        calculate_unit_economics(product, "Москва", replace(logistics, coverage_status="complete"), settings)


def test_negative_tax_base_is_clamped_without_credit():
    case = ORACLE["real_cached_cases"][0]
    values = {**case["input"], "cost": "1000", "tax_system": "usn_income_minus_expenses", "income_tax_rate": "0.06"}
    product, logistics, settings = inputs(values)
    result = calculate_unit_economics(product, "Москва", logistics, settings)
    assert result.calculation_bases.income_tax_base < 0
    assert result.income_tax == 0


def test_coinvest_and_fixed_fbo_are_not_double_counted():
    case = next(c for c in ORACLE["formula_derived_cases"] if c["id"] == "formula_usn_income_vat_coinvest")
    result = calculate(case)
    values = case["input"]
    with localcontext() as context:
        context.prec = 40
        assert result.co_invest == result.price * D(values["co_invest_rate"])
        assert result.realization == result.price - result.co_invest
        assert result.ozon_withholdings == result.commission + result.acquiring + result.expected_logistics + result.advertising_and_services
        assert result.expected_logistics == ((result.base_delivery_tariff + result.fixed_fbo_fee) / D(values["buyout_rate"])
                                             + (D("1") / D(values["buyout_rate"]) - D("1")) * result.base_delivery_tariff)
        assert result.profit_per_unit == result.payout - result.tax - result.cost
