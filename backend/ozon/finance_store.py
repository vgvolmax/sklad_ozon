"""Bounded process-memory finance snapshots; no raw reports or cost history."""
from collections import OrderedDict
from threading import RLock


class FinanceSnapshotStore:
    def __init__(self):
        self._items = OrderedDict()
        self._lock = RLock()

    def put(self, snapshot):
        with self._lock:
            self._items[snapshot.snapshot_id] = snapshot
            while len(self._items) > 3:
                self._items.popitem(last=False)

    def get(self, snapshot_id):
        with self._lock:
            return self._items.get(snapshot_id)

    def clear(self):
        with self._lock:
            self._items.clear()
