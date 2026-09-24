from backend.decision.snapshot import _total_ozon_recommendation


def test_total_ozon_recommendation_requires_every_decision_row():
    from types import SimpleNamespace
    row = lambda quantity: SimpleNamespace(need=SimpleNamespace(ozon_recommended_qty=quantity))
    assert _total_ozon_recommendation((row(0), row(12))) == 12
    assert _total_ozon_recommendation((row(0), row(None))) is None
    assert _total_ozon_recommendation((row(0), row(0))) == 0
