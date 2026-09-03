from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.decision import FlowView, HorizonComparability, NeedComparison
from backend.decision.explanations import explain_decision
from backend.decision.snapshot import (_is_incomplete_row, _route_aggregate,
                                       _views, first_nonblank)


def test_flow_view_rejects_non_business_mode():
    with pytest.raises(ValueError):
        FlowView("global", "all", 0, None, None, 0, ())


def test_horizon_explanation_is_localized_and_keeps_exact_values():
    need = NeedComparison(
        "SKU", "Москва", Decimal("1"), 67, Decimal("9.571428571428571428571428571"),
        0, 0, True, 10, 8, 56, -2, Decimal("-0.25"),
        HorizonComparability.DIFFERENT_HORIZON, True, (),
    )

    explanations = explain_decision(need=need, status_codes=())

    assert explanations == ("Горизонты различаются: Ozon 56 дней, наш расчёт 67 дней.",)


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
    ) for sku, margin, rubles in (
        ("A", Decimal("0"), Decimal("9")),
        ("B", Decimal("10"), Decimal("2")),
    ))
    view = next(item for item in _views(flows, (), opportunities)
                if item.mode == "destination")
    link = view.links[0]
    assert link.margin_delta_pp is None
    assert link.observed_profit_opportunity_rub == Decimal("11")
    assert sum(item.quantity for item in link.sku_breakdown) == link.quantity == view.total_quantity
    assert sum(item.route_share for item in link.sku_breakdown) == Decimal("1")
    assert sum(item.destination_share for item in view.links) == Decimal("1")


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
