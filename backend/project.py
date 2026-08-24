"""Explicit, versioned and atomic Project JSON persistence boundary."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import tempfile
from datetime import date

from backend.domain.contracts import ProductEconomicsInput, ReportMeta, TariffRow

SCHEMA_VERSION = 1
_TOP_FIELDS = {"schema_version", "tariffs", "tariff_meta", "product_economics", "product_economics_meta", "seller_available_stock", "manual_cluster_mappings", "economics_settings", "optimizer_thresholds", "operational_snapshots"}
_FORBIDDEN = {"buyer_name", "customer_name", "address", "phone", "email", "inn", "kpp", "raw_row", "raw_report", "raw_bytes", "raw_csv", "raw_xlsx", "base64_report", "payment_data"}
_SNAPSHOT_FIELDS = {
    "availability": {"sku", "warehouse", "cluster", "available_quantity"},
    "restrictions": {"sku", "warehouse", "state", "reason", "source_value"},
    "orders": {"sku", "quantity", "origin_cluster", "destination_cluster", "lifecycle", "accepted_at", "planned_ship_at", "handed_to_delivery_at", "delivered_at", "raw_status", "article", "product_name", "seller_price", "origin_warehouse", "volumetric_weight_kg"},
}
_SNAPSHOT_REQUIRED = {
    "availability": {"sku", "warehouse", "cluster", "available_quantity"},
    "restrictions": {"sku", "warehouse", "state"},
    "orders": {"sku", "quantity", "origin_cluster", "destination_cluster", "lifecycle", "accepted_at"},
}


class ProjectValidationError(ValueError): pass


@dataclass(frozen=True, slots=True)
class EconomicsSettings:
    acquiring_rate: Decimal; advertising_rate: Decimal; buyout_rate: Decimal; fixed_fbo_fee: Decimal
    tax_system: str; income_tax_rate: Decimal; vat_rate: Decimal; co_invest_rate: Decimal


@dataclass(frozen=True, slots=True)
class OptimizerThresholds:
    min_profit_per_unit: Decimal; min_margin_rate: Decimal; min_roi: Decimal


@dataclass(frozen=True, slots=True)
class OperationalSnapshot:
    kind: str
    report_date: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    records: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class Project:
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    tariffs: tuple[TariffRow, ...] = ()
    tariff_meta: ReportMeta | None = None
    product_economics: tuple[ProductEconomicsInput, ...] = ()
    product_economics_meta: ReportMeta | None = None
    seller_available_stock: dict[str, int] = field(default_factory=dict)
    manual_cluster_mappings: dict[str, str] = field(default_factory=dict)
    economics_settings: EconomicsSettings | None = None
    optimizer_thresholds: OptimizerThresholds | None = None
    operational_snapshots: tuple[OperationalSnapshot, ...] = ()


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)): raise ProjectValidationError("Decimal values must be canonical strings or integers.")
    try: result = Decimal(str(value))
    except InvalidOperation: raise ProjectValidationError("Malformed decimal.") from None
    if not result.is_finite(): raise ProjectValidationError("Decimal must be finite.")
    return result


def _decimal_json(value: Decimal | None) -> str | None:
    if value is None: return None
    value = _decimal(value)
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _meta_json(meta):
    if meta is None: return None
    return {name: getattr(meta, name) for name in ("source_name", "imported_at", "report_generated_at", "period_start", "period_end", "recommendation_horizon_days")}


def _validate_snapshot(snapshot: OperationalSnapshot):
    if snapshot.kind not in _SNAPSHOT_FIELDS: raise ProjectValidationError("Unknown operational snapshot kind.")
    if not (snapshot.report_date or (snapshot.period_start and snapshot.period_end)): raise ProjectValidationError("Operational snapshots require an explicit date or period.")
    try:
        for value in (snapshot.report_date, snapshot.period_start, snapshot.period_end):
            if value is not None: date.fromisoformat(value)
    except (TypeError, ValueError): raise ProjectValidationError("Snapshot dates must use ISO YYYY-MM-DD.") from None
    allowed = _SNAPSHOT_FIELDS[snapshot.kind]
    for record in snapshot.records:
        if not isinstance(record, dict): raise ProjectValidationError("Snapshot records must be objects.")
        unknown = set(record) - allowed
        if unknown: raise ProjectValidationError(f"Unknown or forbidden snapshot fields: {sorted(unknown)}")
        if _SNAPSHOT_REQUIRED[snapshot.kind] - set(record): raise ProjectValidationError("Snapshot record is missing required normalized fields.")
        if not all(value is None or isinstance(value, (str, int, float, bool)) for value in record.values()): raise ProjectValidationError("Snapshot values must be normalized scalars.")


def _validate(project: Project):
    if type(project) is not Project or project.schema_version != 1: raise ProjectValidationError("Unsupported project schema version.")
    for row in project.tariffs:
        for value in (row.min_volume_liters, row.max_volume_liters, row.min_price, row.max_price, row.logistics_fee):
            if value is not None: _decimal(value)
        if not row.origin_cluster_id or not row.destination_cluster_id or row.min_volume_liters < 0 or row.logistics_fee < 0 or row.min_price is not None and row.min_price < 0: raise ProjectValidationError("Invalid tariff.")
        if row.max_volume_liters is not None and row.max_volume_liters < row.min_volume_liters: raise ProjectValidationError("Invalid tariff interval.")
        if row.max_price is not None and (row.max_price < 0 or row.min_price is not None and row.max_price < row.min_price): raise ProjectValidationError("Invalid tariff price interval.")
    for item in project.product_economics:
        if not item.sku or item.available_qty is not None and (type(item.available_qty) is not int or item.available_qty < 0): raise ProjectValidationError("Invalid product economics.")
        for value in (item.cost, item.price, item.volume_liters):
            if value is not None and _decimal(value) < 0: raise ProjectValidationError("Invalid product economics decimal.")
        if item.commission_rate is not None and not 0 <= _decimal(item.commission_rate) <= 1: raise ProjectValidationError("Invalid commission rate.")
    if any(type(qty) is not int or qty < 0 for qty in project.seller_available_stock.values()): raise ProjectValidationError("Invalid seller stock.")
    if not all(isinstance(sku, str) and sku and type(qty) is int for sku, qty in project.seller_available_stock.items()): raise ProjectValidationError("Invalid seller stock keys.")
    if not all(isinstance(source, str) and source and isinstance(target, str) and target for source, target in project.manual_cluster_mappings.items()): raise ProjectValidationError("Invalid manual mapping.")
    for meta in (project.tariff_meta, project.product_economics_meta):
        if meta is not None and (type(meta) is not ReportMeta or not isinstance(meta.source_name, str) or not isinstance(meta.imported_at, str)): raise ProjectValidationError("Invalid report metadata.")
    if project.economics_settings and project.economics_settings.tax_system not in {"usn_income", "usn_income_minus_expenses", "osno", "manual"}: raise ProjectValidationError("Unknown tax system.")
    if project.economics_settings:
        for name in EconomicsSettings.__slots__:
            if name != "tax_system" and (_decimal(getattr(project.economics_settings, name)) < 0 or name.endswith("_rate") and getattr(project.economics_settings, name) > 1): raise ProjectValidationError("Invalid economics setting.")
    if project.optimizer_thresholds:
        for name in OptimizerThresholds.__slots__: _decimal(getattr(project.optimizer_thresholds, name))
    for snapshot in project.operational_snapshots: _validate_snapshot(snapshot)


def _to_payload(project: Project):
    _validate(project)
    payload = {
        "schema_version": 1,
        "tariffs": [{"origin_cluster_id": r.origin_cluster_id, "destination_cluster_id": r.destination_cluster_id, "min_volume_liters": _decimal_json(r.min_volume_liters), "max_volume_liters": _decimal_json(r.max_volume_liters), "min_price": _decimal_json(r.min_price), "max_price": _decimal_json(r.max_price), "logistics_fee": _decimal_json(r.logistics_fee)} for r in project.tariffs],
        "tariff_meta": _meta_json(project.tariff_meta),
        "product_economics": [{"sku": r.sku, "article": r.article, "cost": _decimal_json(r.cost), "available_qty": r.available_qty, "price": _decimal_json(r.price), "commission_rate": _decimal_json(r.commission_rate), "volume_liters": _decimal_json(r.volume_liters)} for r in project.product_economics],
        "product_economics_meta": _meta_json(project.product_economics_meta),
        "seller_available_stock": project.seller_available_stock,
        "manual_cluster_mappings": project.manual_cluster_mappings,
        "economics_settings": None if project.economics_settings is None else {name: (getattr(project.economics_settings, name) if name == "tax_system" else _decimal_json(getattr(project.economics_settings, name))) for name in EconomicsSettings.__slots__},
        "optimizer_thresholds": None if project.optimizer_thresholds is None else {name: _decimal_json(getattr(project.optimizer_thresholds, name)) for name in OptimizerThresholds.__slots__},
        "operational_snapshots": [{"kind": s.kind, "report_date": s.report_date, "period_start": s.period_start, "period_end": s.period_end, "records": list(s.records)} for s in project.operational_snapshots],
    }
    _reject_forbidden_keys(payload)
    return payload


def save_project_atomic(path: Path, project: Project) -> None:
    payload = _to_payload(project)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name); stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path); temporary = None
    finally:
        if temporary is not None:
            try: temporary.unlink()
            except FileNotFoundError: pass


def _strict(value, allowed, context, *, require_all=True):
    if not isinstance(value, dict): raise ProjectValidationError(f"{context} must be an object.")
    unknown = set(value) - set(allowed)
    if unknown or set(value) & _FORBIDDEN: raise ProjectValidationError(f"Unknown or forbidden {context} fields: {sorted(unknown)}")
    if require_all and set(allowed) - set(value): raise ProjectValidationError(f"Missing {context} fields: {sorted(set(allowed) - set(value))}")


def _reject_forbidden_keys(value):
    if isinstance(value, dict):
        forbidden = {str(key).casefold() for key in value} & _FORBIDDEN
        if forbidden: raise ProjectValidationError(f"Forbidden persistence fields: {sorted(forbidden)}")
        for nested in value.values(): _reject_forbidden_keys(nested)
    elif isinstance(value, list):
        for nested in value: _reject_forbidden_keys(nested)


def _meta(value):
    if value is None: return None
    names = ReportMeta.__slots__; _strict(value, names, "metadata")
    try: return ReportMeta(**value)
    except TypeError as exc: raise ProjectValidationError("Invalid metadata.") from exc


def load_project(path: Path) -> Project:
    try: payload = json.loads(Path(path).read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc: raise ProjectValidationError("Project is not valid UTF-8 JSON.") from exc
    _reject_forbidden_keys(payload); _strict(payload, _TOP_FIELDS, "project")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1: raise ProjectValidationError("Missing or unsupported schema version.")
    if not isinstance(payload["tariffs"], list) or not isinstance(payload["product_economics"], list) or not isinstance(payload["operational_snapshots"], list): raise ProjectValidationError("Project collections must be lists.")
    tariffs = []
    for raw in payload["tariffs"]:
        names = TariffRow.__slots__; _strict(raw, names, "tariff")
        tariffs.append(TariffRow(raw["origin_cluster_id"], raw["destination_cluster_id"], _decimal(raw["min_volume_liters"]), None if raw["max_volume_liters"] is None else _decimal(raw["max_volume_liters"]), None if raw["min_price"] is None else _decimal(raw["min_price"]), None if raw["max_price"] is None else _decimal(raw["max_price"]), _decimal(raw["logistics_fee"])))
    products = []
    for raw in payload["product_economics"]:
        names = ProductEconomicsInput.__slots__; _strict(raw, names, "product economics")
        products.append(ProductEconomicsInput(raw["sku"], raw["article"], None if raw["cost"] is None else _decimal(raw["cost"]), raw["available_qty"], None if raw["price"] is None else _decimal(raw["price"]), None if raw["commission_rate"] is None else _decimal(raw["commission_rate"]), None if raw["volume_liters"] is None else _decimal(raw["volume_liters"])))
    econ = payload["economics_settings"]
    if econ is not None:
        _strict(econ, EconomicsSettings.__slots__, "economics settings"); econ = EconomicsSettings(**{k: (v if k == "tax_system" else _decimal(v)) for k, v in econ.items()})
    thresholds = payload["optimizer_thresholds"]
    if thresholds is not None:
        _strict(thresholds, OptimizerThresholds.__slots__, "optimizer thresholds"); thresholds = OptimizerThresholds(**{k: _decimal(v) for k, v in thresholds.items()})
    snapshots = []
    for raw in payload["operational_snapshots"]:
        _strict(raw, OperationalSnapshot.__slots__, "snapshot")
        if not isinstance(raw["records"], list): raise ProjectValidationError("Snapshot records must be a list.")
        snapshots.append(OperationalSnapshot(raw["kind"], raw["report_date"], raw["period_start"], raw["period_end"], tuple(raw["records"])))
    if not isinstance(payload["seller_available_stock"], dict) or not isinstance(payload["manual_cluster_mappings"], dict): raise ProjectValidationError("Stock and mappings must be objects.")
    if not all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in payload["manual_cluster_mappings"].items()): raise ProjectValidationError("Manual mappings must contain nonblank strings.")
    project = Project(tuple(tariffs), _meta(payload["tariff_meta"]), tuple(products), _meta(payload["product_economics_meta"]), payload["seller_available_stock"], payload["manual_cluster_mappings"], econ, thresholds, tuple(snapshots))
    _validate(project); return project
