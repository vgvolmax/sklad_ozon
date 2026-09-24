from datetime import date

import pytest

from backend.ozon.adapters.local_sale import fetch_recommended_supply, supply_period_for_days
from backend.ozon.endpoints import LOCAL_SALE_ITEMS_CLUSTERS_PATH
from backend.ozon.source_contracts import Cluster


@pytest.mark.parametrize('days,period', [(7, 'ONE_WEEK'), (14, 'TWO_WEEKS'),
                                         (28, 'FOUR_WEEKS'), (56, 'EIGHT_WEEKS'),
                                         (21, None)])
def test_only_supported_horizons_have_exact_supply_period(days, period):
    assert supply_period_for_days(days) == period


def test_recommendations_page_and_batch_by_real_sku_and_exact_cluster():
    calls = []

    class Client:
        def post_json(self, path, body, **kwargs):
            calls.append((path, body))
            sku = body['filter']['skus'][0]
            if sku == '1' and body['offset'] == 0:
                return {'items': [{'sku': '1', 'macrolocal_cluster_to_id': 9,
                                   'metrics': {'recommended_supply': 0}}], 'total': 2}
            if sku == '1':
                return {'items': [{'sku': '1', 'macrolocal_cluster_to_id': 10,
                                   'metrics': {'recommended_supply': 16}}], 'total': 2}
            return {'items': [], 'total': 0}

    result = fetch_recommended_supply(Client(), ('1', '2'),
        (Cluster(9, 'Москва'), Cluster(10, 'Казань')),
        date(2026, 7, 1), date(2026, 9, 1), 56, limit=1, batch_size=1)
    assert {(x.sku, x.cluster_id): x.quantity for x in result.items} == {
        ('1', 'Москва'): 0, ('1', 'Казань'): 16}
    assert all(path == LOCAL_SALE_ITEMS_CLUSTERS_PATH for path, _ in calls)
    assert [body['offset'] for _, body in calls] == [0, 1, 0]
    assert all(body['filter']['supply_period'] == 'EIGHT_WEEKS' and
               body['filter']['delivery_schema'] == 'FBO' and
               body['filter']['period'] == {'from': '2026-07-01', 'to': '2026-09-01'}
               for _, body in calls)


def test_conflicting_or_incomplete_recommendations_fail_closed():
    class Client:
        def post_json(self, path, body, **kwargs):
            return {'items': [{'sku': '1', 'macrolocal_cluster_to_id': 9,
                               'metrics': {'recommended_supply': 1}},
                              {'sku': '1', 'macrolocal_cluster_to_id': 9,
                               'metrics': {'recommended_supply': 2}}], 'total': 2}

    with pytest.raises(ValueError, match='conflicting'):
        fetch_recommended_supply(Client(), ('1',), (Cluster(9, 'Москва'),),
                                 date(2026, 7, 1), date(2026, 9, 1), 56)


def test_missing_page_is_not_a_zero_recommendation():
    class Client:
        def post_json(self, path, body, **kwargs):
            return {'items': [], 'total': 1}

    with pytest.raises(ValueError, match='incomplete'):
        fetch_recommended_supply(Client(), ('1',), (Cluster(9, 'Москва'),),
                                 date(2026, 7, 1), date(2026, 9, 1), 56)
