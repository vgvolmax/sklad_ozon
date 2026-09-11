from types import SimpleNamespace

from backend.application import safe_plan_comparable
from backend.decision import HorizonComparability


def need(quantity, comparability):
    return SimpleNamespace(
        ozon_recommended_qty=quantity,
        comparability=comparability,
    )


def test_safe_plan_comparability_requires_nonempty_same_horizon_scope():
    assert safe_plan_comparable((
        need(0, HorizonComparability.SAME_HORIZON),
        need(None, HorizonComparability.OZON_RECOMMENDATION_MISSING),
    ))
    assert not safe_plan_comparable(())
    assert not safe_plan_comparable((
        need(None, HorizonComparability.OZON_RECOMMENDATION_MISSING),
    ))


def test_safe_plan_comparability_fails_whole_sku_on_one_incomparable_row():
    assert not safe_plan_comparable((
        need(10, HorizonComparability.SAME_HORIZON),
        need(20, HorizonComparability.DIFFERENT_HORIZON),
    ))
    assert not safe_plan_comparable((
        need(10, HorizonComparability.SAME_HORIZON),
        need(20, HorizonComparability.OZON_HORIZON_UNKNOWN),
    ))
