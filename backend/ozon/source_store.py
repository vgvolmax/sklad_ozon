"""Bounded process-memory Ozon source snapshot storage."""

from collections import OrderedDict

from .source_contracts import OzonSourceSnapshot


def is_healthy_source_snapshot(snapshot: OzonSourceSnapshot) -> bool:
    """Classify a snapshot only for retention of a clean fallback."""
    return bool(snapshot.endpoint_evidence) and all(
        evidence.complete for evidence in snapshot.endpoint_evidence
    )


class OzonSourceSnapshotStore:
    def __init__(self, max_snapshots: int = 3) -> None:
        if isinstance(max_snapshots, bool) or not isinstance(max_snapshots, int) or max_snapshots < 1:
            raise ValueError("max_snapshots must be a positive integer")
        self._max_snapshots = max_snapshots
        self._snapshots: OrderedDict[str, OzonSourceSnapshot] = OrderedDict()
        self._last_healthy_snapshot_id: str | None = None

    def put(self, snapshot: OzonSourceSnapshot) -> None:
        self._snapshots.pop(snapshot.source_snapshot_id, None)
        self._snapshots[snapshot.source_snapshot_id] = snapshot

        if is_healthy_source_snapshot(snapshot):
            self._last_healthy_snapshot_id = snapshot.source_snapshot_id
        elif self._last_healthy_snapshot_id == snapshot.source_snapshot_id:
            self._last_healthy_snapshot_id = self._find_latest_healthy_snapshot_id()

        while len(self._snapshots) > self._max_snapshots:
            eviction_id = next(
                identity
                for identity in self._snapshots
                if identity != self._last_healthy_snapshot_id
            )
            del self._snapshots[eviction_id]

    def get(self, source_snapshot_id: str) -> OzonSourceSnapshot | None:
        return self._snapshots.get(source_snapshot_id)

    def require(self, source_snapshot_id: str) -> OzonSourceSnapshot:
        snapshot = self.get(source_snapshot_id)
        if snapshot is None:
            raise KeyError(source_snapshot_id)
        return snapshot

    def last_healthy(self) -> OzonSourceSnapshot | None:
        if self._last_healthy_snapshot_id is None:
            return None
        return self._snapshots.get(self._last_healthy_snapshot_id)

    def latest(self) -> OzonSourceSnapshot | None:
        return next(reversed(self._snapshots.values()), None) if self._snapshots else None

    def clear(self) -> None:
        self._snapshots.clear()
        self._last_healthy_snapshot_id = None

    def _find_latest_healthy_snapshot_id(self) -> str | None:
        for identity, candidate in reversed(self._snapshots.items()):
            if is_healthy_source_snapshot(candidate):
                return identity
        return None

    def __len__(self) -> int:
        return len(self._snapshots)
