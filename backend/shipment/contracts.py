"""Immutable contracts for local shipment composition."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


def _nonblank(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _id_tuple(value: object, name: str, item_type: type) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{name} must be a tuple")
    for item in value:
        if item_type is int:
            _positive_int(item, name)
        else:
            _nonblank(item, name)
    if len(value) != len(set(value)):
        raise ValueError(f"{name} must be unique")


def _decimal(value: object, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


class ShipmentMethod(str, Enum):
    PVZ_CROSSDOCK = "pvz_crossdock"
    SC_CROSSDOCK = "sc_crossdock"
    DIRECT = "direct"


@dataclass(frozen=True, slots=True)
class ShipmentScenario:
    selected_cluster_ids: tuple[str, ...]
    date_from: date
    date_to: date
    allowed_methods: tuple[ShipmentMethod, ...]
    preferred_clusters_per_shipment: int
    max_clusters_per_shipment: int
    seller_warehouse_id: int | None = None
    selected_handoff_point_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _id_tuple(self.selected_cluster_ids, "selected_cluster_ids", str)
        if type(self.date_from) is not date or type(self.date_to) is not date:
            raise TypeError("shipment dates must be date values")
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        if not isinstance(self.allowed_methods, tuple) or not self.allowed_methods:
            raise ValueError("allowed_methods must be a nonempty tuple")
        if any(not isinstance(item, ShipmentMethod) for item in self.allowed_methods):
            raise TypeError("allowed_methods must contain ShipmentMethod values")
        if len(self.allowed_methods) != len(set(self.allowed_methods)):
            raise ValueError("allowed_methods must be unique")
        _positive_int(self.preferred_clusters_per_shipment,
                      "preferred_clusters_per_shipment")
        _positive_int(self.max_clusters_per_shipment, "max_clusters_per_shipment")
        if self.preferred_clusters_per_shipment > self.max_clusters_per_shipment:
            raise ValueError("preferred_clusters_per_shipment must not exceed max")
        if self.seller_warehouse_id is not None:
            _positive_int(self.seller_warehouse_id, "seller_warehouse_id")
        _id_tuple(self.selected_handoff_point_ids, "selected_handoff_point_ids", int)


@dataclass(frozen=True, slots=True)
class MethodRule:
    method: ShipmentMethod
    hard_max_clusters: int
    requires_handoff_point: bool
    requires_seller_warehouse: bool
    preliminary_max_shipment_item_volume_l: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.method, ShipmentMethod):
            raise TypeError("method must be ShipmentMethod")
        _positive_int(self.hard_max_clusters, "hard_max_clusters")
        if not isinstance(self.requires_handoff_point, bool) or not isinstance(
                self.requires_seller_warehouse, bool):
            raise TypeError("method requirements must be bool")
        if self.preliminary_max_shipment_item_volume_l is not None:
            _decimal(self.preliminary_max_shipment_item_volume_l,
                     "preliminary_max_shipment_item_volume_l")


@dataclass(frozen=True, slots=True)
class CandidateAssignment:
    sku: str
    article: str
    destination_cluster_id: str
    quantity: int
    pack_multiple: int
    unit_volume_l: Decimal
    total_volume_l: Decimal
    placement_zone_kind: str
    placement_zones: tuple[str, ...]

    def __post_init__(self) -> None:
        _nonblank(self.sku, "sku")
        if not isinstance(self.article, str):
            raise TypeError("article must be a string")
        _nonblank(self.destination_cluster_id, "destination_cluster_id")
        _positive_int(self.quantity, "quantity")
        _positive_int(self.pack_multiple, "pack_multiple")
        if self.quantity % self.pack_multiple:
            raise ValueError("quantity must be divisible by pack_multiple")
        _decimal(self.unit_volume_l, "unit_volume_l")
        _decimal(self.total_volume_l, "total_volume_l")
        if self.total_volume_l != self.unit_volume_l * self.quantity:
            raise ValueError("total_volume_l must equal unit_volume_l * quantity")
        _nonblank(self.placement_zone_kind, "placement_zone_kind")
        _id_tuple(self.placement_zones, "placement_zones", str)


@dataclass(frozen=True, slots=True)
class CandidateShipment:
    candidate_id: str
    method: ShipmentMethod
    seller_warehouse_id: int | None
    handoff_point_id: int | None
    handoff_warehouse_type: str | None
    cluster_ids: tuple[str, ...]
    assignments: tuple[CandidateAssignment, ...]
    total_qty: int
    total_volume_l: Decimal
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _nonblank(self.candidate_id, "candidate_id")
        if not isinstance(self.method, ShipmentMethod):
            raise TypeError("method must be ShipmentMethod")
        for name in ("seller_warehouse_id", "handoff_point_id"):
            value = getattr(self, name)
            if value is not None:
                _positive_int(value, name)
        if self.handoff_warehouse_type is not None:
            _nonblank(self.handoff_warehouse_type, "handoff_warehouse_type")
        _id_tuple(self.cluster_ids, "cluster_ids", str)
        if not self.cluster_ids:
            raise ValueError("cluster_ids must not be empty")
        if not isinstance(self.assignments, tuple) or not self.assignments:
            raise ValueError("assignments must be a nonempty tuple")
        if any(not isinstance(item, CandidateAssignment) for item in self.assignments):
            raise TypeError("assignments must contain CandidateAssignment values")
        if {item.destination_cluster_id for item in self.assignments} != set(self.cluster_ids):
            raise ValueError("assignments must exactly cover cluster_ids")
        _positive_int(self.total_qty, "total_qty")
        _decimal(self.total_volume_l, "total_volume_l")
        if self.total_qty != sum(item.quantity for item in self.assignments):
            raise ValueError("total_qty must equal assignment quantities")
        if self.total_volume_l != sum(
                (item.total_volume_l for item in self.assignments), Decimal("0")):
            raise ValueError("total_volume_l must equal assignment volumes")
        _id_tuple(self.reason_codes, "reason_codes", str)


@dataclass(frozen=True, slots=True)
class ShipmentDiagnostic:
    code: str
    method: ShipmentMethod | None = None
    destination_cluster_id: str | None = None

    def __post_init__(self) -> None:
        _nonblank(self.code, "code")
        if self.method is not None and not isinstance(self.method, ShipmentMethod):
            raise TypeError("method must be ShipmentMethod")
        if self.destination_cluster_id is not None:
            _nonblank(self.destination_cluster_id, "destination_cluster_id")


@dataclass(frozen=True, slots=True)
class CandidateBuildResult:
    candidates: tuple[CandidateShipment, ...]
    diagnostics: tuple[ShipmentDiagnostic, ...]


METHOD_RULES = {
    ShipmentMethod.DIRECT: MethodRule(ShipmentMethod.DIRECT, 1, False, False, None),
    ShipmentMethod.PVZ_CROSSDOCK: MethodRule(
        ShipmentMethod.PVZ_CROSSDOCK, 20, True, True, Decimal("1000")),
    ShipmentMethod.SC_CROSSDOCK: MethodRule(
        ShipmentMethod.SC_CROSSDOCK, 20, True, True, None),
}
