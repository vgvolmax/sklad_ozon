"""Small restart-ephemeral store for immutable completed analysis snapshots."""

from collections import OrderedDict

from backend.decision.contracts import AnalysisSnapshot


class AnalysisSnapshotStore:
    def __init__(self, max_snapshots: int = 3) -> None:
        if isinstance(max_snapshots, bool) or not isinstance(max_snapshots, int) or max_snapshots < 1:
            raise ValueError("max_snapshots must be a positive integer")
        self._max_snapshots = max_snapshots
        self._snapshots: OrderedDict[str, AnalysisSnapshot] = OrderedDict()

    def put(self, snapshot: AnalysisSnapshot) -> None:
        self._snapshots.pop(snapshot.snapshot_id, None)
        self._snapshots[snapshot.snapshot_id] = snapshot
        while len(self._snapshots) > self._max_snapshots:
            self._snapshots.popitem(last=False)

    def get(self, snapshot_id: str) -> AnalysisSnapshot | None:
        return self._snapshots.get(snapshot_id)

    def clear(self) -> None:
        self._snapshots.clear()

    def __len__(self) -> int:
        return len(self._snapshots)
