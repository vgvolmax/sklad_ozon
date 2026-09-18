from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.decision import FlowView, HorizonComparability, NeedComparison
from backend.decision.explanations import explain_decision
from backend.decision.snapshot import (_is_incomplete_row, _route_aggregate,
                                       _observed_demand_qty,
                                       _signal_status_codes,
                                       _total_safe_plan_qty, _views,
                                       first_nonblank)
from backend.analytics._weeks import AnalyticsWindow


def _demand_window(start, end):
    return AnalyticsWindow(end, end.isocalendar().year, end.isocalendar().week,
                           (), 0, 0, 0, start, end, True)


def _point(sku, cluster, day, quantity, origin=None):
    return SimpleNamespace(
        sku=sku, destination_cluster_id=cluster, day=day,
        destination_demand_qty=quantity, origin_cluster_id=origin,
    )


def _observed(points, *, days, start, complete=True, cluster="Краснодар"):
    as_of = date(2026, 9, 18)
    return _observed_demand_qty(
        points, sku="SKU", destination_cluster_id=cluster,
        analysis_as_of=as_of, days=days,
        demand_window=_demand_window(start, as_of),
        demand_complete=complete,
    )


def test_observed_demand_uses_inclusive_calendar_days_including_current_week():
    as_of = date(2026, 9, 18)
    points = tuple(_point("SKU", "Краснодар", day, qty) for day, qty in (
        (date(2026, 9, 11), 100), (date(2026, 9, 12), 2),
        (date(2026, 9, 15), 3), (as_of, 4),
    ))

    assert _observed(points, days=7, start=date(2026, 7, 1)) == 9


def test_observed_demand_56_day_boundary_is_exact():
    as_of = date(2026, 9, 18)
    points = (
        _point("SKU", "Краснодар", as_of - timedelta(days=55), 5),
        _point("SKU", "Краснодар", as_of - timedelta(days=56), 100),
    )

    assert _observed(points, days=56, start=date(2026, 7, 1)) == 5


def test_observed_demand_uses_destination_not_fulfillment_origin():
    as_of = date(2026, 9, 18)
    points = (_point("SKU", "Краснодар", as_of, 5, origin="Москва"),)
    start = date(2026, 7, 1)

    assert _observed(points, days=56, start=start, cluster="Краснодар") == 5
    assert _observed(points, days=56, start=start, cluster="Москва") == 0


def test_observed_demand_preserves_zero_and_fails_closed_per_window():
    as_of = date(2026, 9, 18)
    ninety_day_start = as_of - timedelta(days=89)
    points = (_point("SKU", "Краснодар", as_of, 34),)

    assert _observed((), days=56, start=ninety_day_start) == 0
    assert _observed(points, days=56, start=ninety_day_start) == 34
    assert _observed(points, days=120, start=ninety_day_start) is None
    assert _observed(points, days=56, start=as_of - timedelta(days=54)) is None


def test_observed_demand_incomplete_sku_fails_closed_and_56_horizon_matches():
    as_of = date(2026, 9, 18)
    points = (_point("SKU", "Краснодар", as_of, 31),)
    start = as_of - timedelta(days=100)

    assert _observed(points, days=56, start=start, complete=False) is None
    assert _observed(points, days=56, start=start) == 31
    assert _observed(points, days=56, start=start) == _observed(
        points, days=56, start=start)


def test_flow_view_rejects_non_business_mode():
    with pytest.raises(ValueError):
        FlowView("global", "all", "observed", 0, None, None, 0, None, ())


def test_horizon_explanation_is_localized_and_keeps_exact_values():
    need = NeedComparison(
        "SKU", "Москва", Decimal("1"), 67, Decimal("9.571428571428571428571428571"),
        0, 0, True, 10, 8, 56, -2, Decimal("-0.25"),
        HorizonComparability.DIFFERENT_HORIZON, True, (),
    )

    explanations = explain_decision(need=need, status_codes=())

    assert explanations == (
        "Safe Plan не рассчитан: рекомендация Ozon относится к горизонту "
        "56 дней, а текущий сценарий — 67 дней.",
    )


def test_unknown_ozon_horizon_explanation_is_safe_specific():
    need = NeedComparison(
        "SKU", "Москва", Decimal("1"), 56, Decimal("8"), 0, 0, True,
        8, 5, None, -3, Decimal("-0.375"),
        HorizonComparability.OZON_HORIZON_UNKNOWN, True, (),
    )

    assert explain_decision(need=need, status_codes=()) == (
        "Safe Plan не рассчитан: горизонт рекомендации Ozon неизвестен, "
        "поэтому её нельзя использовать как числовой потолок.",
    )


def test_need_blocker_explanations_use_canonical_codes():
    need = NeedComparison(
        "SKU", "Москва", None, 56, None, None, None, True, None, None,
        None, None, None, HorizonComparability.OZON_RECOMMENDATION_MISSING,
        False, ("MISSING_DEMAND_ESTIMATE", "MISSING_FBO_STOCK", "MISSING_INBOUND_QTY"),
    )
    text = " ".join(explain_decision(need=need, status_codes=()))
    assert "истории спроса" in text
    assert "остатке FBO" in text
    assert "товарах в пути" in text


@pytest.mark.parametrize("code, fragment", [
    ("NON_POSITIVE_PROFIT", "прибыл"),
    ("BELOW_MIN_PROFIT_PER_UNIT", "прибыл"),
    ("BELOW_MIN_MARGIN_RATE", "маржа"),
    ("BELOW_MIN_ROI", "roi"),
    ("SELLER_STOCK_EXHAUSTED", "распределён"),
    ("PARTIAL_BY_SELLER_STOCK", "частично"),
    ("CALCULATED_NEED_CEILING_ZERO", "не требуется"),
    ("OZON_RECOMMENDATION_CEILING_ZERO", "safe plan"),
])
def test_allocator_reason_explanations_are_business_readable(code, fragment):
    need = NeedComparison(
        "SKU", "Москва", Decimal("1"), 56, Decimal("8"), 0, 0, True,
        0, 8, 56, -8, None, HorizonComparability.SAME_HORIZON, True, (),
    )
    kwargs = ({"safe_reason_codes": (code,)}
              if code == "OZON_RECOMMENDATION_CEILING_ZERO" else {})
    assert fragment in " ".join(explain_decision(
        need=need, status_codes=(code,), **kwargs)).lower()


def test_route_margin_is_quantity_weighted_and_partial_coverage_fails_closed():
    complete = [
        SimpleNamespace(complete=True, observed_qty=90, margin_delta_pp=Decimal("0"),
                        observed_profit_opportunity_rub=Decimal("90")),
        SimpleNamespace(complete=True, observed_qty=10, margin_delta_pp=Decimal("10"),
                        observed_profit_opportunity_rub=Decimal("20")),
    ]
    assert _route_aggregate(complete) == (Decimal("1"), Decimal("110"), True)
    incomplete = complete + [SimpleNamespace(
        complete=False, observed_qty=5, margin_delta_pp=None,
        observed_profit_opportunity_rub=None,
    )]
    assert _route_aggregate(incomplete) == (None, None, False)


def test_multi_sku_flow_does_not_invent_margin_average_and_reconciles():
    flows = tuple(SimpleNamespace(
        sku=sku, origin_cluster_id="Казань", destination_cluster_id="Москва",
        quantity=qty,
    ) for sku, qty in (("A", 9), ("B", 1)))
    opportunities = tuple(SimpleNamespace(
        sku=sku, origin_cluster_id="Казань", destination_cluster_id="Москва",
        complete=True, reason_codes=(), margin_delta_pp=margin,
        observed_profit_opportunity_rub=rubles,
        route_cost_rub=cost, realization_per_unit=realization,
        price_per_unit=price, current_profit_per_unit=current_profit,
        local_route_cost_rub=local_cost, local_profit_per_unit=local_profit,
        profit_delta_per_unit=local_profit-current_profit,
    ) for sku, margin, rubles, cost, realization, price, current_profit, local_cost, local_profit in (
        ("A", Decimal("10"), Decimal("90"), Decimal("20"), Decimal("80"), Decimal("100"), Decimal("10"), Decimal("10"), Decimal("20")),
        ("B", Decimal("10"), Decimal("20"), Decimal("40"), Decimal("160"), Decimal("200"), Decimal("20"), Decimal("20"), Decimal("40")),
    ))
    view = next(item for item in _views(flows, (), opportunities)
                if item.mode == "destination")
    link = view.links[0]
    assert link.margin_delta_pp == Decimal("10")
    assert link.observed_profit_opportunity_rub == Decimal("110")
    assert link.economics.route_cost_rub_per_unit == Decimal("22")
    assert link.economics.route_cost_pct_of_realization == Decimal("0.25")
    assert sum(item.quantity for item in link.sku_breakdown) == link.quantity == view.total_quantity
    assert sum(item.route_share for item in link.sku_breakdown) == Decimal("1")
    assert sum(item.destination_share for item in view.links) == Decimal("1")


def test_clean_breakdown_keeps_observed_audit_value_separate_from_evidence_value():
    flow = SimpleNamespace(sku="A", origin_cluster_id="Казань",
                           destination_cluster_id="Москва", quantity=4)
    opportunity = SimpleNamespace(
        sku="A", origin_cluster_id="Казань", destination_cluster_id="Москва",
        complete=True, reason_codes=(), margin_delta_pp=Decimal("10"),
        observed_qty=10, observed_profit_opportunity_rub=Decimal("1000"),
        route_cost_rub=Decimal("20"), realization_per_unit=Decimal("80"),
        price_per_unit=Decimal("100"), current_profit_per_unit=Decimal("10"),
        local_route_cost_rub=Decimal("10"), local_profit_per_unit=Decimal("110"),
        profit_delta_per_unit=Decimal("100"),
    )
    view = next(v for v in _views((flow,), (), (opportunity,), evidence_source="clean")
                if v.mode == "destination")
    link = view.links[0]
    item = link.sku_breakdown[0]
    assert link.observed_profit_opportunity_rub == Decimal("1000")
    assert link.economics.profit_opportunity_rub == Decimal("400")
    assert item.observed_profit_opportunity_rub == Decimal("1000")
    assert item.profit_opportunity_rub == Decimal("400")


def test_identity_fallback_and_incomplete_row_contract_preserve_real_zero():
    assert first_nonblank("  ", " ECON-ARTICLE ", "fallback") == "ECON-ARTICLE"
    need = SimpleNamespace(complete=True)
    placement = SimpleNamespace(
        economics=SimpleNamespace(complete=True),
        feasibility=SimpleNamespace(allowed=True),
    )
    zero_row = SimpleNamespace(need=need, safe_plan_qty=0, calculated_plan_qty=0)
    assert not _is_incomplete_row(
        zero_row, placement, route_required=False, route_complete=False)
    missing_row = SimpleNamespace(need=need, safe_plan_qty=None, calculated_plan_qty=0)
    assert _is_incomplete_row(
        missing_row, placement, route_required=False, route_complete=True)


def test_safe_summary_fails_closed_without_hiding_valid_zero():
    row = lambda recommendation, safe: SimpleNamespace(
        need=SimpleNamespace(ozon_recommended_qty=recommendation),
        safe_plan_qty=safe,
    )

    assert _total_safe_plan_qty((row(0, 0), row(10, 4))) == 4
    assert _total_safe_plan_qty((row(10, 4), row(20, None))) is None
    assert _total_safe_plan_qty((row(None, None),)) is None


def test_signal_status_projection_matches_complete_decision_identity_only():
    stockout = SimpleNamespace(sku="SKU", destination_cluster_id="Москва")
    distortion = SimpleNamespace(sku="SKU", recommended_cluster_id="Казань")

    assert _signal_status_codes(("SKU", "Москва"), (stockout,), (distortion,)) == {
        "PROBABLE_STOCKOUT"
    }
    assert _signal_status_codes(("SKU", "Казань"), (stockout,), (distortion,)) == {
        "RECOMMENDATION_DISTORTION"
    }
    assert _signal_status_codes(("OTHER", "Москва"), (stockout,), (distortion,)) == set()
