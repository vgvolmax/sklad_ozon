"""Concurrency regressions for credential-session revocation during draft validation."""

from threading import Event, Lock, Thread

from backend.ozon.client import OzonClientError
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.draft_contracts import ValidationState
from backend.ozon.endpoints import (
    DRAFT_CROSSDOCK_CREATE,
    DRAFT_DIRECT_CREATE,
    DRAFT_MULTI_CLUSTER_CREATE,
)
from backend.shipment.contracts import ShipmentMethod
from tests.ozon.test_draft_validation_concurrency import (
    CLUSTERS,
    SCENARIO,
    SuccessfulClient,
    make_service,
)
from tests.ozon.test_supply_drafts import candidate


class RevokedBlockingClient:
    def __init__(self):
        self.create_entered = Event()
        self.release_create = Event()
        self.lock = Lock()
        self.create_calls = 0

    def post_json(self, path, payload, *, policy):
        if path in {DRAFT_DIRECT_CREATE, DRAFT_CROSSDOCK_CREATE, DRAFT_MULTI_CLUSTER_CREATE}:
            with self.lock:
                self.create_calls += 1
                self.create_entered.set()
            assert self.release_create.wait(timeout=2)
            raise OzonClientError(
                OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED,
                "Ozon credential context changed",
            )
        raise AssertionError(path)


def _same_validation(service, *, client=None):
    return service.validate(
        (candidate(ShipmentMethod.DIRECT),),
        SCENARIO,
        provenance="context:analysis:plan:source",
        source_clusters=CLUSTERS,
        client=client,
    )


def test_session_revocation_unblocks_waiters_without_cache_poisoning(monkeypatch):
    revoked = RevokedBlockingClient()
    service = make_service(revoked)
    errors = []
    waiter_is_waiting = Event()

    from backend.ozon import draft_validation

    class TrackingEvent:
        def __init__(self):
            self.event = Event()

        def wait(self, timeout=None):
            waiter_is_waiting.set()
            return self.event.wait(timeout)

        def set(self):
            self.event.set()

    monkeypatch.setattr(draft_validation, "Event", TrackingEvent)

    def run():
        try:
            _same_validation(service)
        except BaseException as exc:
            errors.append(exc)

    owner = Thread(target=run)
    owner.start()
    assert revoked.create_entered.wait(timeout=2)

    waiter = Thread(target=run)
    waiter.start()
    assert waiter_is_waiting.wait(timeout=2)

    revoked.release_create.set()
    for thread in (owner, waiter):
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert revoked.create_calls == 1
    assert len(errors) == 2
    assert all(
        isinstance(error, OzonClientError)
        and error.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED
        for error in errors
    )
    assert service._inflight == {}

    fresh = SuccessfulClient()
    option = _same_validation(service, client=fresh)[0]

    assert option.state is ValidationState.NO_TIMESLOT
    assert fresh.create_calls == 1
