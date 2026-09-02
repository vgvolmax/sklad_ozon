from dataclasses import replace
from decimal import Context, Decimal, ROUND_HALF_EVEN, getcontext, localcontext

import pytest

from backend.analytics.flows import FulfillmentFlowCell
from backend.domain.contracts import ImportResult, ProductEconomicsInput, ReportMeta, TariffRow
from backend.economics import calculate_route_opportunity
from backend.project import EconomicsSettings
from backend.supply.contracts import SupplyFeasibility

D=Decimal
FLOW=FulfillmentFlowCell("X","Казань","Москва",40,D("0.4"),2)
PRODUCT=ProductEconomicsInput("X","A",D("100"),10,D("500"),D("0.1"),D("1"))
SETTINGS=EconomicsSettings(D("0.01"),D("0.02"),D("1"),D("10"),"usn_income",D("0.06"),D("0"),D("0.1"))
FEASIBLE=SupplyFeasibility("X","Москва",True,None,("W",),())

def tariffs(current="50",local="20", include_current=True, include_local=True):
    rows=[]
    if include_current: rows.append(TariffRow("Казань","Москва",D("0"),None,None,None,D(current)))
    if include_local: rows.append(TariffRow("Москва","Москва",D("0"),None,None,None,D(local)))
    return ImportResult(tuple(rows),(),ReportMeta("t","now"))


def test_complete_current_vs_local_formulas_and_negative_effects():
    result=calculate_route_opportunity(FLOW,PRODUCT,tariffs(),SETTINGS,FEASIBLE)
    assert result.complete and result.reason_codes==()
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        assert result.route_cost_pct_of_realization==result.route_cost_rub/(PRODUCT.price*(D("1")-SETTINGS.co_invest_rate))
        assert result.margin_delta_pp==(result.local_margin_rate-result.current_margin_rate)*D("100")
        assert result.observed_profit_opportunity_rub==result.profit_delta_per_unit*D(result.observed_qty)
    worse=calculate_route_opportunity(FLOW,PRODUCT,tariffs(local="80"),SETTINGS,FEASIBLE)
    assert worse.margin_delta_pp < 0 and worse.profit_delta_per_unit < 0 and worse.observed_profit_opportunity_rub < 0


@pytest.mark.parametrize("feasibility",[replace(FEASIBLE,allowed=False),replace(FEASIBLE,max_supply_qty=0)])
def test_infeasible_local_retains_current(feasibility):
    result=calculate_route_opportunity(FLOW,PRODUCT,tariffs(),SETTINGS,feasibility)
    assert result.route_cost_rub is not None and result.current_profit_per_unit is not None
    assert result.local_route_cost_rub is result.margin_delta_pp is None
    assert not result.complete and result.reason_codes==("LOCAL_PLACEMENT_INFEASIBLE",)


def test_missing_current_or_local_tariff_fails_closed():
    current=calculate_route_opportunity(FLOW,PRODUCT,tariffs(include_current=False),SETTINGS,FEASIBLE)
    assert current.route_cost_rub is current.current_profit_per_unit is current.local_route_cost_rub is None
    assert "CURRENT_ROUTE_INCOMPLETE" in current.reason_codes
    local=calculate_route_opportunity(FLOW,PRODUCT,tariffs(include_local=False),SETTINGS,FEASIBLE)
    assert local.route_cost_rub is not None and local.current_profit_per_unit is not None
    assert local.local_route_cost_rub is local.profit_delta_per_unit is None
    assert "LOCAL_ROUTE_INCOMPLETE" in local.reason_codes


def test_zero_realization_and_context_isolation():
    old=getcontext().prec
    try:
        getcontext().prec=2
        product=replace(PRODUCT,price=D("0"))
        result=calculate_route_opportunity(FLOW,product,tariffs(),SETTINGS,FEASIBLE)
        assert not result.complete and result.route_cost_pct_of_realization is None
        assert "MISSING_OR_ZERO_REALIZATION" in result.reason_codes
        assert getcontext().prec==2
    finally: getcontext().prec=old


def test_identity_mismatch_fails_fast():
    with pytest.raises(ValueError): calculate_route_opportunity(FLOW,replace(PRODUCT,sku="Y"),tariffs(),SETTINGS,FEASIBLE)
    with pytest.raises(ValueError): calculate_route_opportunity(FLOW,PRODUCT,tariffs(),SETTINGS,replace(FEASIBLE,cluster_id="Казань"))
