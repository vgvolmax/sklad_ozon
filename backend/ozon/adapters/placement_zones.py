"""Exact Ozon placement-zone evidence; no inferred substitutes."""

from backend.domain.contracts import ImportDiagnostic
from backend.ozon.adapters.wire import sku as parse_sku
from backend.ozon.client import OzonRequestPolicy
from backend.ozon.endpoints import PLACEMENT_ZONE_PATH
from backend.ozon.source_contracts import OzonRecordQualityEvidence, PlacementZoneEvidence

READ = OzonRequestPolicy(retry_safe=True)


def normalize_placement_zones(response: dict):
    if "products_placement" not in response or not isinstance(response["products_placement"], list):
        raise ValueError("invalid placement-zone response")
    evidence, diagnostics, incomplete = {}, [], set(); rejected = 0
    for raw in response["products_placement"]:
        if not isinstance(raw, dict): raise ValueError("invalid placement-zone record")
        try: sku = parse_sku(raw.get("sku"))
        except ValueError as exc: raise ValueError("invalid placement-zone SKU") from exc
        value = raw.get("placement_zone")
        zone = value.strip() if isinstance(value, str) else ""
        valid = bool(zone and zone != "UNSPECIFIED")
        current = PlacementZoneEvidence(sku, (zone,) if valid else (), valid)
        previous = evidence.get(sku)
        if previous is not None and previous != current:
            if sku not in incomplete: rejected += 1
            incomplete.add(sku); evidence[sku] = PlacementZoneEvidence(sku, (), False)
            diagnostics.append(ImportDiagnostic("warning", "UNKNOWN_PLACEMENT_ZONE", f"Conflicting placement zone for SKU {sku}"))
        elif previous is None:
            evidence[sku] = current
            if not valid:
                rejected += 1; incomplete.add(sku)
                diagnostics.append(ImportDiagnostic("warning", "UNKNOWN_PLACEMENT_ZONE", f"Placement zone is unknown for SKU {sku}"))
    return tuple(evidence.values()), tuple(diagnostics), OzonRecordQualityEvidence(rejected, tuple(sorted(incomplete)))


def fetch_placement_zones(client, skus: tuple[str, ...], progress_callback=None):
    records, diagnostics, incomplete = [], [], set(); rejected = 0
    if progress_callback: progress_callback(current=0, total=len(skus), unit="sku")
    for start in range(0, len(skus), 100):
        batch = skus[start:start + 100]
        part, part_diagnostics, quality = normalize_placement_zones(
            client.post_json(PLACEMENT_ZONE_PATH, {"skus": list(batch)}, policy=READ))
        returned = {row.sku for row in part}
        if not returned.issubset(batch): raise ValueError("placement zones returned unrequested SKU")
        by_sku = {row.sku: row for row in part}
        for missing in sorted(set(batch) - returned):
            by_sku[missing] = PlacementZoneEvidence(missing, (), False)
            diagnostics.append(ImportDiagnostic("warning", "UNKNOWN_PLACEMENT_ZONE", f"Placement zone is missing for SKU {missing}"))
            incomplete.add(missing); rejected += 1
        records.extend(by_sku[sku] for sku in batch)
        diagnostics.extend(part_diagnostics); incomplete.update(quality.incomplete_skus); rejected += quality.rejected_record_count
        if progress_callback:
            progress_callback(current=min(start + len(batch), len(skus)), total=len(skus), unit="sku")
    return tuple(records), tuple(diagnostics), OzonRecordQualityEvidence(rejected, tuple(sorted(incomplete)))
