from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

import backend.application
from backend.economics.workspace_pricing import enrich_pricing
from tests.economics.test_pricing import inputs, settings, tariffs, tier


@pytest.mark.parametrize('role', ['origin', 'destination'])
@pytest.mark.parametrize('covered_above_boundary', [True, False])
def test_group_target_rechecks_all_routes_at_the_proposed_price(role, covered_above_boundary):
    pairs = [('A', 'B'), ('A', 'C')] if role == 'origin' else [('A', 'C'), ('B', 'C')]
    rows = [tier(*pairs[0], '10', upper='150'), tier(*pairs[1], '30')]
    if covered_above_boundary:
        rows.append(tier(*pairs[0], '1000', lower='150'))
    product = inputs()
    snapshot = NS(snapshot_id='group-target', economics_tariffs=tariffs(*rows),
        economics_pricing_inputs=(product,), economics_settings=settings(),
        route_economics=tuple(NS(sku=product.sku, origin_cluster_id=o,
            destination_cluster_id=d, observed_qty=1) for o, d in pairs))
    selected = [dict(origin=o, destination=d, qty=1) for o, d in pairs]
    period = {'from': date(2026, 9, 1), 'to': date(2026, 9, 30)}
    report = dict(period=period, observation_period=period, target_margin=D('.2'),
        target_roi=D('.4'), goal='margin', products=[dict(sku=product.sku,
            applied_drr_rate=D('.05'), planned_drr_rate=D('.05'), buyer_prices=None,
            groups={'destination': [dict(routes=selected)], 'origin': []})])
    enrich_pricing(snapshot, report, {})
    p = report['products'][0]
    group = next(g for g in p['groups'][role] if len(g['routes']) == 2)
    expected = D('2418.61') if covered_above_boundary else None
    assert group['target_price_all_routes'] == expected
    assert p['target_price_all_routes'] == expected
