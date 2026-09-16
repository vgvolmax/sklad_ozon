from dataclasses import replace
from datetime import date, datetime, timezone

from backend.ozon.draft_contracts import ValidationState
from backend.ozon.draft_validation import (
    DRAFT_RESUME_TTL_SECONDS,
    MAX_INFO_POLL_ATTEMPTS,
    VALIDATION_CACHE_TTL_SECONDS,
    DraftValidationService,
)
from backend.ozon.endpoints import (
    DRAFT_CREATE_INFO,
    DRAFT_CROSSDOCK_CREATE,
    DRAFT_DIRECT_CREATE,
    DRAFT_MULTI_CLUSTER_CREATE,
    DRAFT_TIMESLOT_INFO,
)
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
CREATE_PATHS = {
    DRAFT_DIRECT_CREATE,
    DRAFT_CROSSDOCK_CREATE,
    DRAFT_MULTI_CLUSTER_CREATE,
}


def make_service(client, now):
    return DraftValidationService(
        client,
        clock=lambda: now[0],
        today=lambda: date(2026, 9, 10),
        utcnow=lambda: datetime(2026, 9, 10, tzinfo=timezone.utc),
        sleeper=lambda _: None,
    )


def validate_one(service, row, *, provenance="p"):
    return service.validate(
        (row,),
        SCENARIO,
        provenance=provenance,
        source_clusters=CLUSTERS,
    )[0]


class MalformedCreateEvidenceClient:
    def __init__(self):
        self.calls = []
        self.create_calls = 0

    def post_json(self, path, payload, *, policy):
        self.calls.append((path, payload, policy))
        if path in CREATE_PATHS:
            self.create_calls += 1
            if self.create_calls == 1:
                return {"draft_id": 7, "errors": None}
            return {"draft_id": 8, "errors": []}
        if path == DRAFT_CREATE_INFO:
            return info()
        if path == DRAFT_TIMESLOT_INFO:
            return slots(None)
        raise AssertionError(path)


def test_valid_draft_id_survives_malformed_create_evidence():
    now = [0.0]
    client = MalformedCreateEvidenceClient()
    service = make_service(client, now)
    row = candidate(ShipmentMethod.DIRECT)

    first = validate_one(service, row)
    assert first.state is ValidationState.UNAVAILABLE
    assert first.reason_codes == ("OZON_INVALID_DRAFT_RESPONSE",)

    now[0] = VALIDATION_CACHE_TTL_SECONDS + 1
    calls_before_retry = len(client.calls)
    second = validate_one(service, row)

    assert second.state is ValidationState.NO_TIMESLOT
    assert client.calls[calls_before_retry][0] == DRAFT_CREATE_INFO
    assert client.calls[calls_before_retry][1] == {"draft_id": 7}
    assert client.create_calls == 1


class PendingThenResolvedClient:
    def __init__(self):
        self.calls = []
        self.next_draft_id = 1

    def post_json(self, path, payload, *, policy):
        self.calls.append((path, payload, policy))
        if path in CREATE_PATHS:
            draft_id = self.next_draft_id
            self.next_draft_id += 1
            return {"draft_id": draft_id, "errors": []}
        if path == DRAFT_CREATE_INFO:
            draft_id = payload["draft_id"]
            if draft_id in {1, 2}:
                return {"status": "IN_PROGRESS", "clusters": [], "errors": []}
            return info()
        if path == DRAFT_TIMESLOT_INFO:
            return slots(None)
        raise AssertionError(path)


def test_expired_resumable_registry_entries_are_swept_globally():
    now = [0.0]
    client = PendingThenResolvedClient()
    service = make_service(client, now)
    base = candidate(ShipmentMethod.DIRECT)
    a = replace(base, candidate_id="A")
    b = replace(base, candidate_id="B")
    c = replace(base, candidate_id="C")

    assert validate_one(service, a).reason_codes == ("DRAFT_INFO_TIMEOUT",)
    assert validate_one(service, b).reason_codes == ("DRAFT_INFO_TIMEOUT",)
    assert len(service._resumable_drafts) == 2

    now[0] = DRAFT_RESUME_TTL_SECONDS + 1
    resolved = validate_one(service, c)

    assert resolved.state is ValidationState.NO_TIMESLOT
    assert service._resumable_drafts == {}
