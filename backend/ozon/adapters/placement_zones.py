"""Exact Ozon placement-zone evidence; no inferred substitutes."""

from backend.domain.contracts import ImportDiagnostic
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import PLACEMENT_ZONE_PATH
from backend.ozon.source_contracts import PlacementZoneEvidence

READ = OzonRequestPolicy(retry_safe=True)


def normalize_placement_zones(response: dict):
    result = response.get("result", response)
    items = result.get("items", result.get("products", [])) if isinstance(result, dict) else []
    records = []
    diagnostics = []
    for raw in items:
        sku = str(raw.get("sku", raw.get("product_id", ""))).strip()
        source = raw.get("placement_zones", raw.get("zones", raw.get("placement_zone")))
        if isinstance(source, str):
            zones = (source.strip(),) if source.strip() else ()
        elif isinstance(source, list):
            zones = tuple(dict.fromkeys(str(x.get("name", x.get("zone", "")) if isinstance(x, dict) else x).strip()
                                        for x in source))
            zones = tuple(x for x in zones if x)
        else:
            zones = ()
        if not sku:
            diagnostics.append(ImportDiagnostic("error", "INVALID_PLACEMENT_ZONE", "Placement-zone SKU is missing"))
            continue
        if not zones:
            diagnostics.append(ImportDiagnostic("warning", "UNKNOWN_PLACEMENT_ZONE", f"Placement zone is unknown for SKU {sku}"))
        records.append(PlacementZoneEvidence(sku, zones, bool(zones)))
    return tuple(records), tuple(diagnostics)


def fetch_placement_zones(client: OzonClient, skus: tuple[str, ...]):
    records = []
    diagnostics = []
    for start in range(0, len(skus), 1000):
        response = client.post_json(PLACEMENT_ZONE_PATH, {"product_ids":list(skus[start:start+1000])}, policy=READ)
        part, part_diagnostics = normalize_placement_zones(response)
        records.extend(part); diagnostics.extend(part_diagnostics)
    return tuple(records), tuple(diagnostics)
