"""Small restart-ephemeral store for immutable completed analysis snapshots."""

from collections import OrderedDict

from backend.decision.contracts import AnalysisSnapshot
from .contracts import ShipmentPlan


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

class ShipmentPlanStore:
    def __init__(self,max_plans: int=8):
        if isinstance(max_plans,bool) or not isinstance(max_plans,int) or max_plans<1: raise ValueError("max_plans must be a positive integer")
        self._max_plans=max_plans; self._plans=OrderedDict()
    def put(self,plan: ShipmentPlan):
        self._plans.pop(plan.shipment_plan_id,None); self._plans[plan.shipment_plan_id]=plan
        while len(self._plans)>self._max_plans:self._plans.popitem(last=False)
    def get(self,shipment_plan_id): return self._plans.get(shipment_plan_id)
    def clear(self): self._plans.clear()
    def __len__(self): return len(self._plans)
