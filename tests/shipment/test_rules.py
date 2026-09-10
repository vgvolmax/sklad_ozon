from backend.shipment.contracts import ShipmentMethod
from backend.shipment.rules import placement_reason
from backend.supply.contracts import PlacementZoneKind


def test_unknown_and_pvz_kgt_are_conservatively_blocked(line_factory):
    unknown = line_factory("s", "c", 1, zone_kind=PlacementZoneKind.UNKNOWN, zones=())
    kgt = line_factory("s", "c", 1, zones=("KGT",))
    assert placement_reason(unknown, ShipmentMethod.DIRECT) == "PLACEMENT_ZONE_INCOMPLETE"
    assert placement_reason(kgt, ShipmentMethod.PVZ_CROSSDOCK) == "PLACEMENT_ZONE_UNSUPPORTED"
    assert placement_reason(kgt, ShipmentMethod.SC_CROSSDOCK) is None


def test_multiple_exact_zones_are_preserved_and_not_invented(line_factory):
    line = line_factory("s", "c", 1, zone_kind=PlacementZoneKind.MULTIPLE,
                        zones=("SORTABLE", "NON_SORTABLE"))
    assert placement_reason(line, ShipmentMethod.SC_CROSSDOCK) is None
    assert line.placement_zones == ("SORTABLE", "NON_SORTABLE")
