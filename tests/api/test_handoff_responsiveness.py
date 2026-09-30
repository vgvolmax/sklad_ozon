import asyncio
from threading import Event

import backend.api as api


def test_paced_handoff_search_keeps_the_api_event_loop_responsive(monkeypatch):
    release = Event()
    class Request:
        async def json(self):
            return {'query': 'Москва', 'supply_types': ['direct']}
    def waiting_search(*args):
        release.wait(timeout=2)
        return ()
    monkeypatch.setattr(api, 'search_handoff_points', waiting_search)
    async def exercise():
        search = asyncio.create_task(api.ozon_handoff_search(Request()))
        try:
            await asyncio.sleep(0.02)
            responsive = not search.done()
        finally:
            release.set()
        result = await search
        assert result['items'] == []
        assert responsive, 'Ozon throttling must not block other local API requests'
    asyncio.run(exercise())
