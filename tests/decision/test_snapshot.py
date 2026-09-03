from decimal import Decimal

import pytest

from backend.decision import FlowView, HorizonComparability, NeedComparison
from backend.decision.explanations import explain_decision


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
