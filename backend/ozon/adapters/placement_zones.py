"""Exact Ozon placement-zone evidence; no inferred substitutes."""

from backend.domain.contracts import ImportDiagnostic
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import PLACEMENT_ZONE_PATH
from backend.ozon.source_contracts import PlacementZoneEvidence

READ = OzonRequestPolicy(retry_safe=True)


def normalize_placement_zones(response: dict):
    items = response.get("products_placement", [])
    records = []
    diagnostics = []
    for raw in items if isinstance(items, list) else ():
        sku = str(raw.get("sku", "")).strip()
        zone = str(raw.get("placement_zone") or "").strip()
        complete = bool(zone and zone != "UNSPECIFIED")
        zones = (zone,) if zone else ()
        if not sku:
            diagnostics.append(ImportDiagnostic("error", "INVALID_PLACEMENT_ZONE", "Placement-zone SKU is missing"))
            continue
        if not complete:
            diagnostics.append(ImportDiagnostic("warning", "UNKNOWN_PLACEMENT_ZONE", f"Placement zone is unknown for SKU {sku}"))
        records.append(PlacementZoneEvidence(sku, zones, complete))
    return tuple(records), tuple(diagnostics)


def fetch_placement_zones(client: OzonClient, skus: tuple[str, ...]):
    records = []
    diagnostics = []
    for start in range(0, len(skus), 100):
        response = client.post_json(PLACEMENT_ZONE_PATH, {"skus": list(skus[start:start + 100])}, policy=READ)
        part, part_diagnostics = normalize_placement_zones(response)
        records.extend(part); diagnostics.extend(part_diagnostics)
    return tuple(records), tuple(diagnostics)
