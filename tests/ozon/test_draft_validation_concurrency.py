from dataclasses import replace
from datetime import date, datetime, timezone
from threading import Barrier, Event, Lock, Thread

from backend.ozon.client import OzonClientError
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.draft_contracts import ValidationState
from backend.ozon.draft_validation import DraftValidationService
from backend.ozon.endpoints import DRAFT_CREATE_INFO, DRAFT_CROSSDOCK_CREATE, DRAFT_DIRECT_CREATE, DRAFT_MULTI_CLUSTER_CREATE
from backend.ozon.source_contracts import Cluster
from backend.shipment.contracts import ShipmentMethod, ShipmentScenario
from tests.ozon.test_draft_polling import info, slots
from tests.ozon.test_supply_drafts import candidate


SCENARIO = ShipmentScenario(
    ("Москва",),
    date(2026, 9, 11),
    date(2026, 9, 12),
    (ShipmentMethod.DIRECT,),
    1,
    1,
)
CLUSTERS = (Cluster(111, "Москва"),)


class BlockingSuccessfulClient:
    def __init__(self):
        self.create_entered = Event()
        self.release_create = Event()
        self.lock = Lock()
        self.create_calls = 0

    def post_json(self, path, payload, *, policy):
        if path in {DRAFT_DIRECT_CREATE, DRAFT_CROSSDOCK_CREATE, DRAFT_MULTI_CLUSTER_CREATE}:
            with self.lock:
                self.create_calls += 1
                draft_id = self.create_calls
                self.create_entered.set()
            assert self.release_create.wait(timeout=2)
            return {"draft_id": draft_id, "errors": []}
        if path.endswith("/create/info"):
            return info()
        return slots([])


class SuccessfulClient:
    def __init__(self, create_barrier=None):
        self.create_barrier = create_barrier
        self.lock = Lock()
        self.create_calls = 0

    def post_json(self, path, payload, *, policy):
        if path in {DRAFT_DIRECT_CREATE, DRAFT_CROSSDOCK_CREATE, DRAFT_MULTI_CLUSTER_CREATE}:
            with self.lock:
                self.create_calls += 1
                draft_id = self.create_calls
            if self.create_barrier is not None:
                self.create_barrier.wait()
            return {"draft_id": draft_id, "errors": []}
        if path == DRAFT_CREATE_INFO:
            return info()
        return slots([])


def make_service(client):
    return DraftValidationService(
        client,
        clock=lambda: 0,
        today=lambda: date(2026, 9, 10),
        utcnow=lambda: datetime(2026, 9, 10, tzinfo=timezone.utc),
        sleeper=lambda _: None,
    )


def call_validate(service, barrier, output):
    barrier.wait()
    output.append(
        service.validate(
            (candidate(ShipmentMethod.DIRECT),),
            SCENARIO,
            provenance="context:analysis:plan:source",
            source_clusters=CLUSTERS,
        )[0]
    )


def test_concurrent_same_candidate_uses_one_external_create(monkeypatch):
    client = BlockingSuccessfulClient()
    service = make_service(client)
    barrier = Barrier(3)
    preparation_barrier = Barrier(2)
    output = []
    from backend.ozon import draft_validation

    original_resolver = draft_validation.resolve_candidate_cluster_identities

    def synchronized_resolver(*args):
        result = original_resolver(*args)
        preparation_barrier.wait()
        return result

    monkeypatch.setattr(draft_validation, "resolve_candidate_cluster_identities", synchronized_resolver)
    threads = [Thread(target=call_validate, args=(service, barrier, output)) for _ in range(2)]

    for thread in threads:
        thread.start()
    barrier.wait()
    assert client.create_entered.wait(timeout=2)
    client.release_create.set()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert client.create_calls == 1
    assert len(output) == 2
    assert output[0] == output[1]
    assert output[0].state is ValidationState.NO_TIMESLOT


def test_concurrent_different_keys_reserve_only_two_minute_slots(monkeypatch):
    client = SuccessfulClient(create_barrier=Barrier(2))
    service = make_service(client)
    start = Barrier(4)
    preparation = Barrier(3)
    output = []
    lock = Lock()
    from backend.ozon import draft_validation

    original_resolver = draft_validation.resolve_candidate_cluster_identities

    def synchronized_resolver(*args):
        result = original_resolver(*args)
        preparation.wait()
        return result

    monkeypatch.setattr(draft_validation, "resolve_candidate_cluster_identities", synchronized_resolver)

    def run(candidate_id):
        start.wait()
        option = service.validate(
            (replace(candidate(ShipmentMethod.DIRECT), candidate_id=candidate_id),),
            SCENARIO,
            provenance="context",
            source_clusters=CLUSTERS,
        )[0]
        with lock:
            output.append(option)

    threads = [Thread(target=run, args=(str(index),)) for index in range(3)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert client.create_calls == 2
    assert sum(option.state is ValidationState.RATE_LIMITED for option in output) == 1
    limited = next(option for option in output if option.state is ValidationState.RATE_LIMITED)
    assert limited.reason_codes == ("DRAFT_RATE_BUDGET_EXHAUSTED",)


def test_ambiguous_create_is_single_flight_and_quarantined(monkeypatch):
    class Client(BlockingSuccessfulClient):
        def post_json(self, path, payload, *, policy):
            if path in {DRAFT_DIRECT_CREATE, DRAFT_CROSSDOCK_CREATE, DRAFT_MULTI_CLUSTER_CREATE}:
                with self.lock:
                    self.create_calls += 1
                    self.create_entered.set()
                assert self.release_create.wait(timeout=2)
                raise OzonClientError(OzonErrorCode.UNAVAILABLE, "lost")
            raise AssertionError(path)

    client = Client()
    service = make_service(client)
    start = Barrier(3)
    preparation = Barrier(2)
    output = []
    from backend.ozon import draft_validation

    original_resolver = draft_validation.resolve_candidate_cluster_identities

    def synchronized_resolver(*args):
        result = original_resolver(*args)
        preparation.wait()
        return result

    monkeypatch.setattr(draft_validation, "resolve_candidate_cluster_identities", synchronized_resolver)
    threads = [Thread(target=call_validate, args=(service, start, output)) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    assert client.create_entered.wait(timeout=2)
    client.release_create.set()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert client.create_calls == 1
    assert [option.state for option in output] == [ValidationState.OUTCOME_UNKNOWN] * 2
    cached = service.validate(
        (candidate(ShipmentMethod.DIRECT),), SCENARIO, provenance="context:analysis:plan:source", source_clusters=CLUSTERS
    )[0]
    assert cached.state is ValidationState.OUTCOME_UNKNOWN
    assert client.create_calls == 1


def test_rate_limited_candidate_resumes_after_rolling_minute():
    now = [0.0]
    client = SuccessfulClient()
    service = DraftValidationService(
        client,
        clock=lambda: now[0],
        today=lambda: date(2026, 9, 10),
        utcnow=lambda: datetime(2026, 9, 10, tzinfo=timezone.utc),
        sleeper=lambda _: None,
    )
    candidates = tuple(replace(candidate(ShipmentMethod.DIRECT), candidate_id=value) for value in ("A", "B", "C"))

    first = service.validate(candidates, SCENARIO, provenance="context", source_clusters=CLUSTERS)
    assert [option.state for option in first] == [ValidationState.NO_TIMESLOT, ValidationState.NO_TIMESLOT, ValidationState.RATE_LIMITED]
    now[0] += 61
    second = service.validate(candidates, SCENARIO, provenance="context", source_clusters=CLUSTERS)

    assert [option.state for option in second] == [ValidationState.NO_TIMESLOT] * 3
    assert client.create_calls == 3


def test_different_provenance_is_not_single_flight():
    client = SuccessfulClient(create_barrier=Barrier(2))
    service = make_service(client)
    start = Barrier(3)
    output = []

    def run(provenance):
        start.wait()
        output.append(service.validate((candidate(ShipmentMethod.DIRECT),), SCENARIO, provenance=provenance, source_clusters=CLUSTERS)[0])

    threads = [Thread(target=run, args=(provenance,)) for provenance in ("credential:A", "credential:B")]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert client.create_calls == 2
    assert len(output) == 2


def test_cancelled_waiter_does_not_cancel_owner_or_create_again():
    client = BlockingSuccessfulClient()
    service = make_service(client)
    owner_output = []
    waiter_output = []
    owner = Thread(target=lambda: owner_output.extend(call_one(service)))
    owner.start()
    assert client.create_entered.wait(timeout=2)
    waiter = Thread(target=lambda: waiter_output.extend(call_one(service, cancelled=lambda: True)))
    waiter.start()
    waiter.join(timeout=2)
    assert not waiter.is_alive()
    assert waiter_output[0].state is ValidationState.UNAVAILABLE
    assert waiter_output[0].reason_codes == ("VALIDATION_CANCELLED",)
    assert owner.is_alive()
    client.release_create.set()
    owner.join(timeout=2)
    assert not owner.is_alive()
    assert owner_output[0].state is ValidationState.NO_TIMESLOT
    assert client.create_calls == 1
    assert service._inflight == {}


def call_one(service, *, cancelled=lambda: False):
    return service.validate(
        (candidate(ShipmentMethod.DIRECT),),
        SCENARIO,
        provenance="context:analysis:plan:source",
        source_clusters=CLUSTERS,
        cancelled=cancelled,
    )


def test_owner_exception_unblocks_waiter_and_clears_inflight(monkeypatch):
    class Client(BlockingSuccessfulClient):
        def post_json(self, path, payload, *, policy):
            if path in {DRAFT_DIRECT_CREATE, DRAFT_CROSSDOCK_CREATE, DRAFT_MULTI_CLUSTER_CREATE}:
                with self.lock:
                    self.create_calls += 1
                    self.create_entered.set()
                assert self.release_create.wait(timeout=2)
                raise RuntimeError("unexpected")
            raise AssertionError(path)

    client = Client()
    service = make_service(client)
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
            call_one(service)
        except BaseException as exc:
            errors.append(exc)

    owner = Thread(target=run)
    owner.start()
    assert client.create_entered.wait(timeout=2)
    waiter = Thread(target=run)
    waiter.start()
    assert waiter_is_waiting.wait(timeout=2)
    client.release_create.set()
    for thread in (owner, waiter):
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert client.create_calls == 1
    assert len(errors) == 2
    assert all(isinstance(error, RuntimeError) and str(error) == "unexpected" for error in errors)
    assert service._inflight == {}
