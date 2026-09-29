from dataclasses import replace
from types import SimpleNamespace

import backend.api as api
from backend.ozon.source_contracts import Cluster, EndpointEvidence
from backend.ozon.sync import OzonRefreshReport
from tests.api.test_analysis import _api_parity_fixture


def test_sync_does_not_call_recommendation_api(tmp_path, monkeypatch):
    base = _api_parity_fixture()
    source = replace(base, clusters=(Cluster(9, 'Москва'),),
        endpoint_evidence=base.endpoint_evidence +
        (EndpointEvidence('clusters', base.synced_at_utc, 1, True),))
    monkeypatch.setattr(api, 'OZON_SOURCE_PATH', tmp_path / 'source.json')
    monkeypatch.setattr(api.OZON_CLIENT, 'bind_context', lambda _context: object())
    monkeypatch.setattr(api, 'refresh_ozon_source', lambda *_args, **_kwargs: (
        source, OzonRefreshReport('full','full',None,(),(),(),None)))
    monkeypatch.setattr('backend.ozon.adapters.local_sale.fetch_recommended_supply', lambda *_args:
        (_ for _ in ()).throw(AssertionError('Recommendation API called')))
    monkeypatch.setattr(api, 'commit_active_credential_context',
                        lambda _context, action: action())
    result = api._refresh_response(SimpleNamespace(context_id=source.credential_context_id), 'full')
    assert all(item['name'] != 'recommended_supply'
               for item in result['source']['endpoint_evidence'])
    assert result['capabilities']['ozon_comparison']['complete'] is False
    assert api.load_source_snapshot_if_exists(api.OZON_SOURCE_PATH).recommended_supply is None
