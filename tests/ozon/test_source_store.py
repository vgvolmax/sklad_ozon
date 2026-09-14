from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone

import pytest

from backend.domain.contracts import SourceMode
from backend.ozon.source_contracts import (
    EndpointEvidence,
    OzonSourceSnapshot,
    source_business_date,
)
from backend.ozon.source_store import (
    OzonSourceSnapshotStore,
    is_healthy_source_snapshot,
)


def endpoint(name: str, complete: bool, *, record_count: int = 0) -> EndpointEvidence:
    return EndpointEvidence(
        name=name,
        fetched_at_utc="2026-09-14T00:00:00+00:00",
        record_count=record_count,
        complete=complete,
    )


def snap(identity: str, *, healthy: bool = True, diagnostics=()) -> OzonSourceSnapshot:
    return OzonSourceSnapshot(
        identity,
        "x",
        date(2026, 1, 1),
        "UTC+03:00",
        date(2025, 1, 1),
        date(2026, 1, 1),
        (),
        (),
        (),
        (),
        (),
        (),
        (endpoint("orders", healthy),),
        diagnostics,
    )


def test_source_contract_and_bounded_identity_store():
    assert (SourceMode.API.value, SourceMode.FILES.value) == ("api", "files")
    assert source_business_date(
        datetime(2026, 1, 1, 21, 1, tzinfo=timezone.utc)
    ) == date(2026, 1, 2)
    store = OzonSourceSnapshotStore(2)
    for identity in "abc":
        store.put(snap(identity))
    assert store.get("a") is None
    assert store.require("c").source_snapshot_id == "c"
    with pytest.raises(FrozenInstanceError):
        store.require("c").source_timezone = "x"
    store.clear()
    assert len(store) == 0
    assert store.get("c") is None


def test_last_healthy_snapshot_survives_partial_refresh_eviction():
    store = OzonSourceSnapshotStore(3)
    store.put(snap("healthy"))
    for number in range(1, 5):
        store.put(snap(f"partial-{number}", healthy=False))

    assert store.get("healthy") is not None
    assert store.last_healthy().source_snapshot_id == "healthy"
    assert len(store) == 3


def test_new_healthy_snapshot_replaces_protected_fallback():
    store = OzonSourceSnapshotStore(3)
    store.put(snap("healthy-a"))
    store.put(snap("partial", healthy=False))
    store.put(snap("healthy-b"))
    store.put(snap("partial-2", healthy=False))
    store.put(snap("partial-3", healthy=False))

    assert store.last_healthy().source_snapshot_id == "healthy-b"
    assert store.get("healthy-a") is None


def test_healthy_snapshots_retain_normal_fifo_semantics():
    store = OzonSourceSnapshotStore(2)
    for identity in "ABC":
        store.put(snap(identity))

    assert store.get("A") is None
    assert store.get("B") is not None
    assert store.get("C") is not None


def test_clear_resets_last_healthy_snapshot():
    store = OzonSourceSnapshotStore()
    store.put(snap("healthy"))
    store.clear()

    assert store.last_healthy() is None
    assert store.get("healthy") is None
    assert len(store) == 0


def test_health_uses_complete_evidence_not_diagnostics_or_record_count():
    warning_only = snap("warning", diagnostics=({"severity": "warning"},))
    empty_complete = snap("empty")

    assert is_healthy_source_snapshot(warning_only) is True
    assert is_healthy_source_snapshot(empty_complete) is True


def test_one_incomplete_endpoint_makes_snapshot_unhealthy_for_retention():
    snapshot = replace(
        snap("partial"),
        endpoint_evidence=(endpoint("orders", True), endpoint("inbound", False)),
    )

    assert is_healthy_source_snapshot(snapshot) is False


def test_snapshot_without_endpoint_evidence_is_not_healthy():
    snapshot = replace(snap("no-evidence"), endpoint_evidence=())

    assert is_healthy_source_snapshot(snapshot) is False


def test_tiny_capacity_prefers_healthy_fallback_over_partial_attempt():
    store = OzonSourceSnapshotStore(1)
    store.put(snap("healthy"))
    store.put(snap("partial", healthy=False))

    assert store.get("healthy") is not None
    assert store.get("partial") is None
    assert store.last_healthy().source_snapshot_id == "healthy"
    assert len(store) == 1


def test_replacing_protected_id_recalculates_retention_health():
    store = OzonSourceSnapshotStore(2)
    store.put(snap("healthy-a"))
    store.put(snap("healthy-b"))
    store.put(snap("healthy-b", healthy=False))

    assert store.last_healthy().source_snapshot_id == "healthy-a"


def test_store_remains_bounded_after_many_partial_refreshes():
    store = OzonSourceSnapshotStore(3)
    store.put(snap("healthy"))
    for number in range(100):
        store.put(snap(f"partial-{number}", healthy=False))

    assert len(store) == 3
    assert store.get("healthy") is not None
