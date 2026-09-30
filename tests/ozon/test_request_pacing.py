from datetime import datetime, timezone
from email.utils import format_datetime
from threading import Thread

import pytest

from backend.ozon.client import OzonClient, OzonClientError, OzonRequestPolicy
from backend.ozon.endpoints import FBO_STOCK_PATH
from tests.ozon.test_client import VaultStub, response


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds


def client_with_clock(responses):
    clock, starts = Clock(), []
    replies = iter(responses)
    def transport(request, timeout):
        starts.append((request.full_url.split('.ru')[1], clock.now))
        return next(replies)
    client = OzonClient(VaultStub(), transport=transport,
                        sleeper=clock.sleep, clock=lambda: clock.now,
                        wall_clock=lambda: 1_800_000_000 + clock.now)
    return client, clock, starts


def test_successful_batches_and_bound_clients_share_the_slow_stock_gate():
    client, _, starts = client_with_clock([response()] * 4)
    bound = client.bind_context(VaultStub.context)
    client.post_json(FBO_STOCK_PATH, {}, policy=OzonRequestPolicy(True))
    bound.post_json('/v1/other', {}, policy=OzonRequestPolicy(True))
    bound.post_json(FBO_STOCK_PATH, {}, policy=OzonRequestPolicy(True))
    client.post_json(FBO_STOCK_PATH, {}, policy=OzonRequestPolicy(True))
    assert [time for _, time in starts] == [0, 1.1, 6, 12]


def test_concurrent_callers_cannot_burst_stock_requests():
    client, _, starts = client_with_clock([response()] * 4)
    threads = [Thread(target=lambda: client.post_json(FBO_STOCK_PATH, {}, policy=OzonRequestPolicy(True)))
               for _ in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert [time for _, time in starts] == [0, 6, 12, 18]


def test_rate_limit_cooldown_applies_to_retries_and_subsequent_manual_calls():
    client, _, starts = client_with_clock([response(429), response(429), response()])
    client.post_json('/v1/other', {}, policy=OzonRequestPolicy(True))
    assert [time for _, time in starts] == [0, 10, 30]
    client, _, starts = client_with_clock([response(429), response()])
    with pytest.raises(OzonClientError):
        client.post_json('/v1/draft/create', {}, policy=OzonRequestPolicy(False))
    assert len(starts) == 1
    client.post_json('/v1/other', {}, policy=OzonRequestPolicy(True))
    assert [time for _, time in starts] == [0, 10]


def test_long_retry_after_is_remembered_without_an_early_second_operation():
    client, clock, starts = client_with_clock([response(429, headers={'Retry-After': '120'}), response()])
    for _ in range(2):
        with pytest.raises(OzonClientError):
            client.post_json(FBO_STOCK_PATH, {}, policy=OzonRequestPolicy(True))
    assert len(starts) == 1 and clock.now == 0
    clock.now = 120
    client.post_json(FBO_STOCK_PATH, {}, policy=OzonRequestPolicy(True))
    assert [time for _, time in starts] == [0, 120]


def test_http_date_retry_after_is_respected():
    header = format_datetime(datetime.fromtimestamp(1_800_000_025, timezone.utc), usegmt=True)
    client, _, starts = client_with_clock([response(429, headers={'Retry-After': header}), response()])
    client.post_json('/v1/other', {}, policy=OzonRequestPolicy(True))
    assert [time for _, time in starts] == [0, 25]
