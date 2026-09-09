"""Bounded process-memory Ozon source snapshot storage."""

from collections import OrderedDict

from .source_contracts import OzonSourceSnapshot


class OzonSourceSnapshotStore:
    def __init__(self, max_snapshots: int = 3) -> None:
        if isinstance(max_snapshots, bool) or not isinstance(max_snapshots, int) or max_snapshots < 1:
            raise ValueError("max_snapshots must be a positive integer")
        self._max_snapshots = max_snapshots
        self._snapshots: OrderedDict[str, OzonSourceSnapshot] = OrderedDict()

    def put(self, snapshot: OzonSourceSnapshot) -> None:
        self._snapshots.pop(snapshot.source_snapshot_id, None)
        self._snapshots[snapshot.source_snapshot_id] = snapshot
        while len(self._snapshots) > self._max_snapshots:
            self._snapshots.popitem(last=False)

    def get(self, source_snapshot_id: str) -> OzonSourceSnapshot | None:
        return self._snapshots.get(source_snapshot_id)

    def require(self, source_snapshot_id: str) -> OzonSourceSnapshot:
        snapshot = self.get(source_snapshot_id)
        if snapshot is None:
            raise KeyError(source_snapshot_id)
        return snapshot

    def __len__(self) -> int:
        return len(self._snapshots)
