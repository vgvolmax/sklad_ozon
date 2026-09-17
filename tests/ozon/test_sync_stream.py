import asyncio
import json
from types import SimpleNamespace

import backend.api as api_module
from tests.ozon.test_source_store import snap


def _events(response):
    async def collect():
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(collect())
    assert chunks and all(chunk.endswith("\n") for chunk in chunks)
    return [json.loads(chunk) for chunk in chunks]


def _stream_stubs(monkeypatch, sync):
    context = SimpleNamespace(context_id="ctx")
    monkeypatch.setattr(api_module.OZON_VAULT, "capture_context", lambda: context)
    monkeypatch.setattr(api_module.OZON_CLIENT, "bind_context", lambda value: value)
    monkeypatch.setattr(api_module, "sync_ozon_source", sync)
    monkeypatch.setattr(api_module, "commit_active_credential_context",
                        lambda _context, action: action())


def test_sync_stream_progress_precedes_result_and_is_monotonic(monkeypatch):
    def sync(_client, *, credential_context_id, progress_callback):
        assert credential_context_id == "ctx"
        for index, stage in enumerate(("orders_fbo", "orders_fbs", "clusters"), 1):
            progress_callback({"type": "progress", "stage": stage,
                               "stage_index": index, "stage_count": 9,
                               "label": stage})
        return snap("stream-result")

    _stream_stubs(monkeypatch, sync)
    events = _events(api_module.ozon_sync_stream())

    assert [item["type"] for item in events] == [
        "progress", "progress", "progress", "result"]
    assert [item["stage_index"] for item in events[:-1]] == [1, 2, 3]
    assert events[-1]["data"]["source"]["source_snapshot_id"] == "stream-result"


def test_sync_stream_top_level_failure_ends_with_safe_error(monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("raw secret exception")

    _stream_stubs(monkeypatch, broken)
    events = _events(api_module.ozon_sync_stream())

    assert events == [{"type": "error", "error": {
        "code": "OZON_SYNC_FAILED",
        "message": "Не удалось обновить данные Ozon.",
    }}]
    assert "secret" not in json.dumps(events)
