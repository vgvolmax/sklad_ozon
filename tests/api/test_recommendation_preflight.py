import asyncio
import hashlib
import json
from io import BytesIO

import backend.api as api
from starlette.datastructures import FormData, UploadFile
from tests.api.test_recommendation_xlsx_analysis import recommendation, source


class UploadRequest:
    def __init__(self, report, snapshot_id, horizon=56):
        self.data = FormData({'file': UploadFile(BytesIO(report), filename='report.xlsx'),
                             'source_snapshot_id': snapshot_id, 'horizon_days': str(horizon)})

    async def form(self):
        return self.data


def preflight(report, horizon=56):
    snap = source()
    api.OZON_SOURCE_STORE.put(snap)
    return asyncio.run(api.validate_recommendations(UploadRequest(report, snap.source_snapshot_id, horizon)))


def test_upload_is_checked_before_analysis_without_project_or_ozon_mutation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Preflight must only parse the uploaded file')
    monkeypatch.setattr(api, 'save_project_atomic', forbidden)
    monkeypatch.setattr(api.OZON_CLIENT, 'post_json', forbidden)
    report = recommendation([
        ['SKU-1', 'ART-1', 'Product', 0, '', 'Москва', 'FBO'],
        ['SKU-1', 'ART-1', 'Product', 99, '', 'Unknown', 'FBO'],
    ])
    with monkeypatch.context() as isolated:
        isolated.setattr(api.ANALYSIS_STORE, 'clear', forbidden)
        result = preflight(report)
    assert result['valid'] is True and result['usable_for_comparison'] is True
    assert result['record_count'] == 1 and result['excluded_record_count'] == 1
    assert result['sku_count'] == 1 and result['cluster_count'] == 1
    assert result['content_sha256'] == hashlib.sha256(report).hexdigest()
    assert result['report_meta']['recommendation_horizon_days'] == 56
    assert result['diagnostics'][0]['code'] == 'UNKNOWN_RECOMMENDATION_CLUSTER'


def test_preflight_returns_invalid_and_noncomparable_verdicts_without_a_plan():
    assert preflight(b'not xlsx')['valid'] is False
    report = recommendation([['SKU-1', 'ART-1', 'Product', 3, '', 'Москва', 'FBO']])
    result = preflight(report, horizon=28)
    assert result['valid'] is True and result['usable_for_comparison'] is False
    assert 'Горизонт файла' in result['message']


def test_http_upload_endpoint_exposes_preflight_without_running_analysis():
    from tests.api.test_analysis import CLIENT
    snap = source()
    api.OZON_SOURCE_STORE.put(snap)
    response = CLIENT.post('/api/import/recommendations/validate',
        files={'file': ('report.xlsx', recommendation([
            ['SKU-1', 'ART-1', 'Product', 0, '', 'Москва', 'FBO']]))},
        data={'source_snapshot_id': snap.source_snapshot_id, 'horizon_days': '56'})
    assert response.status_code == 200
    assert response.json()['valid'] is True
    assert response.json()['record_count'] == 1


def test_preflight_rejects_old_source_and_rechecks_source_after_parsing(monkeypatch):
    from dataclasses import replace
    original = source()
    api.OZON_SOURCE_STORE.put(original)
    newer = replace(original, source_snapshot_id='newer-preflight-source')
    api.OZON_SOURCE_STORE.put(newer)
    report = recommendation([['SKU-1', 'ART-1', 'Product', 3, '', 'Москва', 'FBO']])
    response = asyncio.run(api.validate_recommendations(UploadRequest(report, original.source_snapshot_id)))
    assert response.status_code == 409
    assert json.loads(response.body)['error']['code'] == 'OZON_SOURCE_SNAPSHOT_STALE'
    api.OZON_SOURCE_STORE.put(original)
    parse = api.import_recommendation_xlsx
    def changed(*args):
        result = parse(*args)
        api.OZON_SOURCE_STORE.put(newer)
        return result
    monkeypatch.setattr(api, 'import_recommendation_xlsx', changed)
    response = asyncio.run(api.validate_recommendations(UploadRequest(report, original.source_snapshot_id)))
    assert response.status_code == 409
