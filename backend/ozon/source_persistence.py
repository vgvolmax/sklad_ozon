"""Versioned, strict and atomic persistence for normalized Ozon evidence."""

from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import tempfile

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle, OrderRecord
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.adapters.product_facts import ProductApiFacts
from backend.ozon.adapters.local_sale import LocalSaleResult, RecommendedSupply
from backend.ozon.source_contracts import (
    Cluster, EndpointEvidence, OzonApiErrorEvidence, OzonRecordQualityEvidence,
    OzonSourceSnapshot, PlacementZoneEvidence, SellerWarehouse,
)

SOURCE_PERSISTENCE_SCHEMA_VERSION = 2


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def _required(value, name, kind):
    item = _object(value)
    if name not in item or not isinstance(item[name], kind) or isinstance(item[name], bool) and kind is int:
        raise ValueError(f"invalid {name}")
    return item[name]


def _optional(value, name, kind):
    item = _object(value).get(name)
    if item is not None and (not isinstance(item, kind) or isinstance(item, bool) and kind is int):
        raise ValueError(f"invalid {name}")
    return item


def _tuple(value, decoder):
    if not isinstance(value, list):
        raise ValueError("expected array")
    return tuple(decoder(item) for item in value)


def _warehouse_mapping(value):
    if not isinstance(value, list):
        raise ValueError("invalid warehouse_to_macrolocal")
    result = []
    warehouse_mapping = {}
    for pair in value:
        if (not isinstance(pair, list) or len(pair) != 2
                or type(pair[0]) is not int or type(pair[1]) is not int
                or pair[0] <= 0 or pair[1] <= 0):
            raise ValueError("invalid warehouse_to_macrolocal pair")
        warehouse_id, macrolocal_id = pair
        previous = warehouse_mapping.get(warehouse_id)
        if previous is not None and previous != macrolocal_id:
            raise ValueError("conflicting warehouse_to_macrolocal mapping")
        warehouse_mapping[warehouse_id] = macrolocal_id
        result.append((warehouse_id, macrolocal_id))
    return tuple(result)


def _diagnostic(value):
    return ImportDiagnostic(
        _required(value, "severity", str), _required(value, "code", str),
        _required(value, "message", str), _optional(value, "row", int),
        _optional(value, "field", str),
    )


def _api_error(value):
    return OzonApiErrorEvidence(
        _required(value, "code", str), _optional(value, "endpoint", str),
        _optional(value, "http_status", int), _optional(value, "vendor_code", str),
        _optional(value, "vendor_message", str), _optional(value, "request_id", str),
        _optional(value, "transport_kind", str), _optional(value, "attempts", int),
        _optional(value, "elapsed_ms", int),
    )


def _quality(value):
    skus = _required(value, "incomplete_skus", list)
    if not all(isinstance(item, str) for item in skus):
        raise ValueError("invalid incomplete_skus")
    return OzonRecordQualityEvidence(
        _required(value, "rejected_record_count", int), tuple(skus))


def _evidence(value):
    diagnostics = _tuple(_required(value, "diagnostics", list), _diagnostic)
    raw_error = _object(value).get("api_error")
    raw_quality = value.get("record_quality")
    return EndpointEvidence(
        _required(value, "name", str), _required(value, "fetched_at_utc", str),
        _required(value, "record_count", int), _required(value, "complete", bool),
        diagnostics, _api_error(raw_error) if raw_error is not None else None,
        _quality(raw_quality) if raw_quality is not None else None,
    )


def _order(value):
    item = _object(value)
    try:
        lifecycle = OrderLifecycle(_required(item, "lifecycle", str))
    except ValueError as exc:
        raise ValueError("invalid lifecycle") from exc
    return OrderRecord(
        sku=_required(item, "sku", str), quantity=_required(item, "quantity", int),
        origin_cluster=_required(item, "origin_cluster", str),
        destination_cluster=_required(item, "destination_cluster", str), lifecycle=lifecycle,
        accepted_at=_required(item, "accepted_at", str),
        planned_ship_at=_optional(item, "planned_ship_at", str),
        handed_to_delivery_at=_optional(item, "handed_to_delivery_at", str),
        delivered_at=_optional(item, "delivered_at", str), raw_status=_required(item, "raw_status", str),
        article=_required(item, "article", str), product_name=_required(item, "product_name", str),
        seller_price=float(item.get("seller_price", 0.0)),
        origin_warehouse=_optional(item, "origin_warehouse", str),
        volumetric_weight_kg=(None if item.get("volumetric_weight_kg") is None else float(item["volumetric_weight_kg"])),
        source_channel=item.get("source_channel", "") if isinstance(item.get("source_channel", ""), str) else (_ for _ in ()).throw(ValueError("invalid source_channel")),
    )


def _availability(value):
    item = _object(value)
    return AvailabilityRecord(
        _required(item, "sku", str), _required(item, "warehouse", str),
        _required(item, "cluster", str), float(_required(item, "available_quantity", (int, float))),
        _optional(item, "recommended_quantity", int), _required(item, "article", str),
        _optional(item, "fbo_quantity", int), _optional(item, "fbs_quantity", int),
        _required(item, "product_name", str), _optional(item, "days_without_stock", int),
        _optional(item, "inbound_quantity", int),
    )


def _decimal(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("decimal must be a string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid Decimal") from exc
    if not result.is_finite():
        raise ValueError("invalid Decimal")
    return result


def _facts(value):
    item = _object(value)
    return ProductApiFacts(
        _required(item, "sku", str), _required(item, "article", str),
        _required(item, "product_id", int), _decimal(item.get("price")),
        _decimal(item.get("commission_rate")), _decimal(item.get("volume_liters")),
    )


def _recommended_supply(value):
    item = _object(value)
    items = _tuple(_required(item, "items", list), lambda raw: RecommendedSupply(
        _required(raw, "sku", str), _required(raw, "cluster_id", str),
        _required(raw, "quantity", int)))
    if any(row.quantity < 0 for row in items):
        raise ValueError("invalid recommended supply")
    try:
        start = date.fromisoformat(_required(item, "analytics_from", str))
        end = date.fromisoformat(_required(item, "analytics_to", str))
    except ValueError as exc:
        raise ValueError("invalid recommendation period") from exc
    horizon = _required(item, "horizon_days", int)
    period = _required(item, "supply_period", str)
    if horizon != 56 or period != "EIGHT_WEEKS" or start > end:
        raise ValueError("invalid recommendation frequency")
    return LocalSaleResult(items, _required(item, "fetched_at_utc", str),
                           start, end, horizon, period,
                           _required(item, "endpoint", str))


def _encode(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, OrderLifecycle)):
        return value.isoformat() if isinstance(value, date) else value.value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {key: _encode(item) for key, item in asdict(value).items()}
    return value


def source_snapshot_to_document(snapshot: OzonSourceSnapshot) -> dict:
    return {"schema_version": SOURCE_PERSISTENCE_SCHEMA_VERSION, "snapshot": _encode(snapshot)}


def source_snapshot_from_document(document: object) -> OzonSourceSnapshot:
    root = _object(document)
    if root.get("schema_version") != SOURCE_PERSISTENCE_SCHEMA_VERSION:
        raise ValueError("unsupported source snapshot schema")
    item = _object(root.get("snapshot"))
    source_id = _required(item, "source_snapshot_id", str)
    if not source_id.strip():
        raise ValueError("missing source ID")
    try:
        source_as_of = date.fromisoformat(_required(item, "source_as_of", str))
        history_from = date.fromisoformat(_required(item, "history_from", str))
        history_to = date.fromisoformat(_required(item, "history_to", str))
    except ValueError as exc:
        raise ValueError("invalid source date") from exc
    return OzonSourceSnapshot(
        source_id, _required(item, "synced_at_utc", str), source_as_of,
        _required(item, "source_timezone", str), history_from, history_to,
        _tuple(_required(item, "orders", list), _order),
        _tuple(_required(item, "availability", list), _availability),
        _tuple(_required(item, "operational_seller_stock", list), _availability),
        _tuple(_required(item, "clusters", list), lambda x: Cluster(_required(x, "cluster_id", int), _required(x, "name", str))),
        _tuple(_required(item, "seller_warehouses", list), lambda x: SellerWarehouse(_required(x, "seller_warehouse_id", int), _optional(x, "name", str), _optional(x, "address", str), _required(x, "is_active", bool), _optional(x, "is_pickup", bool))),
        _tuple(_required(item, "placement_zones", list), lambda x: PlacementZoneEvidence(_required(x, "sku", str), tuple(_required(x, "zones", list)), _required(x, "complete", bool))),
        _tuple(_required(item, "endpoint_evidence", list), _evidence),
        _tuple(_required(item, "diagnostics", list), _diagnostic),
        _optional(item, "credential_context_id", str),
        _tuple(_required(item, "product_facts", list), _facts),
        _warehouse_mapping(_required(item, "warehouse_to_macrolocal", list)),
        (_recommended_supply(item["recommended_supply"])
         if item.get("recommended_supply") is not None else None),
    )


def save_source_snapshot_atomic(path: Path, snapshot: OzonSourceSnapshot) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(source_snapshot_to_document(snapshot), ensure_ascii=False, separators=(",", ":"))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_source_snapshot_if_exists(path: Path) -> OzonSourceSnapshot | None:
    path = Path(path)
    if not path.exists():
        return None
    return source_snapshot_from_document(json.loads(path.read_text(encoding="utf-8")))


def delete_source_snapshot(path: Path) -> None:
    Path(path).unlink(missing_ok=True)
