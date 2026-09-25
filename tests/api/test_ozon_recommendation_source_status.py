from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import backend.api as api
from backend.ozon.adapters.local_sale import LocalSaleResult, RecommendedSupply
from backend.ozon.client import OzonClientError
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.endpoints import LOCAL_SALE_ITEMS_CLUSTERS_PATH
from backend.ozon.source_contracts import Cluster, EndpointEvidence
from backend.ozon.source_store import is_healthy_source_snapshot
from backend.ozon.sync import OzonRefreshReport
from tests.api.test_analysis import _api_parity_fixture


def test_source_refresh_fetches_exact_default_56_days_without_changing_other_evidence(monkeypatch):
    base = _api_parity_fixture()
    source = replace(base, clusters=(Cluster(9, 'Москва'),),
        endpoint_evidence=base.endpoint_evidence +
        (EndpointEvidence('clusters', base.synced_at_utc, 1, True),))
    calls = []

    def fetch(client, skus, clusters, start, end, horizon):
        calls.append((skus, start, end, horizon))
        return LocalSaleResult((RecommendedSupply('SKU-1', 'Москва', 0),),
                               datetime.now(timezone.utc).isoformat(), start, end,
                               horizon, 'EIGHT_WEEKS')

    monkeypatch.setattr(api, 'fetch_recommended_supply', fetch)
    enriched = api._attach_default_recommendation(source, object())
    evidence = next(item for item in enriched.endpoint_evidence
                    if item.name == 'recommended_supply')
    assert calls == [(('SKU-1',), source.history_from, source.history_to, 56)]
    assert enriched.recommended_supply.items[0].quantity == 0
    assert evidence.complete and evidence.record_count == 1
    assert is_healthy_source_snapshot(enriched) == is_healthy_source_snapshot(source)


def test_recommendation_permission_error_is_visible_but_does_not_block_source(monkeypatch):
    base = _api_parity_fixture()
    source = replace(base, clusters=(Cluster(9, 'Москва'),),
        endpoint_evidence=base.endpoint_evidence +
        (EndpointEvidence('clusters', base.synced_at_utc, 1, True),))

    def denied(*args):
        raise OzonClientError(OzonErrorCode.PERMISSION_DENIED, 'denied',
                              endpoint=LOCAL_SALE_ITEMS_CLUSTERS_PATH,
                              status=403, vendor_code='NO_ACCESS', request_id='request-7')

    monkeypatch.setattr(api, 'fetch_recommended_supply', denied)
    enriched = api._attach_default_recommendation(source, object())
    evidence = next(item for item in enriched.endpoint_evidence
                    if item.name == 'recommended_supply')
    assert enriched.recommended_supply is None
    assert not evidence.complete and evidence.api_error.http_status == 403
    assert evidence.api_error.request_id == 'request-7'
    assert is_healthy_source_snapshot(enriched) == is_healthy_source_snapshot(source)
    assert not api.source_refresh_regresses(
        replace(source, endpoint_evidence=source.endpoint_evidence +
                (replace(evidence, complete=True),)), enriched)


def test_sync_response_includes_default_recommendation_status(tmp_path, monkeypatch):
    base = _api_parity_fixture()
    source = replace(base, clusters=(Cluster(9, 'Москва'),),
        endpoint_evidence=base.endpoint_evidence +
        (EndpointEvidence('clusters', base.synced_at_utc, 1, True),))
    monkeypatch.setattr(api, 'OZON_SOURCE_PATH', tmp_path / 'source.json')
    monkeypatch.setattr(api.OZON_CLIENT, 'bind_context', lambda _context: object())
    monkeypatch.setattr(api, 'refresh_ozon_source', lambda *_args, **_kwargs: (
        source, OzonRefreshReport('full','full',None,(),(),(),None)))
    monkeypatch.setattr(api, 'fetch_recommended_supply', lambda *_args:
        LocalSaleResult((RecommendedSupply('SKU-1', 'Москва', 0),),
                        datetime.now(timezone.utc).isoformat(),
                        source.history_from, source.history_to, 56, 'EIGHT_WEEKS'))
    monkeypatch.setattr(api, 'commit_active_credential_context',
                        lambda _context, action: action())
    result = api._refresh_response(SimpleNamespace(context_id=source.credential_context_id), 'full')
    recommendation = next(item for item in result['source']['endpoint_evidence']
                          if item['name'] == 'recommended_supply')
    assert recommendation['record_count'] == 1
    assert result['capabilities']['ozon_comparison']['complete'] is True
    assert api.load_source_snapshot_if_exists(api.OZON_SOURCE_PATH).recommended_supply.items[0].quantity == 0


def test_old_default_recommendation_is_refetched_for_new_analysis():
    source = _api_parity_fixture()
    old = LocalSaleResult((RecommendedSupply('SKU-1', 'Москва', 0),),
        (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),
        source.history_from, source.history_to, 56, 'EIGHT_WEEKS')
    assert api._current_default_recommendation(replace(source, recommended_supply=old), 56) is None


def test_invalid_recommendation_response_has_distinct_status(monkeypatch):
    base = _api_parity_fixture()
    source = replace(base, clusters=(Cluster(9, 'Москва'),))
    monkeypatch.setattr(api, 'fetch_recommended_supply', lambda *_args:
                        (_ for _ in ()).throw(ValueError('invalid local-sale response')))
    enriched = api._attach_default_recommendation(source, object())
    evidence = enriched.endpoint_evidence[-1]
    assert evidence.diagnostics[0].code == 'OZON_RECOMMENDED_SUPPLY_INVALID_RESPONSE'
    assert enriched.recommended_supply is None
