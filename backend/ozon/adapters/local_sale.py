"""Exact FBO recommended_supply evidence for a selected supply frequency."""

from dataclasses import dataclass
from datetime import date, datetime, timezone

from backend.ozon.adapters.wire import nonnegative_int, positive_int, sku as parse_sku
from backend.ozon.client import OzonRequestPolicy
from backend.ozon.endpoints import LOCAL_SALE_ITEMS_CLUSTERS_PATH

READ = OzonRequestPolicy(retry_safe=True)
SUPPLY_PERIODS = {7: "ONE_WEEK", 14: "TWO_WEEKS", 28: "FOUR_WEEKS", 56: "EIGHT_WEEKS"}
_MISSING = object()


class LocalSaleResponseShapeError(ValueError):
    """A response mismatch described only by JSON types, never by seller values."""


class LocalSaleIdentityError(ValueError):
    """A source identity mismatch with only bounded, safe identifiers."""


def _identity_disagreement(sku: str, cluster_id: int, known: set[str],
                           batch: tuple[str, ...], by_id: dict[int, str]) -> str:
    sku_label = (f"SKU {sku}" if sku.isascii() and sku.isdecimal() and len(sku) <= 20
                 else "SKU нестандартного формата")
    details = []
    if sku not in known:
        details.append(f"{sku_label} отсутствует в текущем каталоге Ozon")
    elif sku not in batch:
        details.append(f"{sku_label} есть в каталоге, но отсутствует в запрошенной партии")
    if cluster_id not in by_id:
        details.append(f"Кластер {cluster_id} отсутствует в текущем каталоге Ozon")
    return "; ".join(details) + "."


def _json_kind(value) -> str:
    if value is _MISSING:
        return "отсутствует"
    if isinstance(value, list):
        return "список"
    if isinstance(value, dict):
        return "объект"
    if type(value) is int:
        return "целое число"
    if isinstance(value, str):
        return "строка"
    if value is None:
        return "null"
    return "другой тип"


def supply_period_for_days(days: int) -> str | None:
    return SUPPLY_PERIODS.get(days) if type(days) is int else None


@dataclass(frozen=True, slots=True)
class RecommendedSupply:
    sku: str
    cluster_id: str
    quantity: int


@dataclass(frozen=True, slots=True)
class LocalSaleResult:
    items: tuple[RecommendedSupply, ...]
    fetched_at_utc: str
    analytics_from: date
    analytics_to: date
    horizon_days: int
    supply_period: str
    endpoint: str = LOCAL_SALE_ITEMS_CLUSTERS_PATH


def fetch_recommended_supply(client, skus, clusters, period_from: date,
                             period_to: date, horizon_days: int, *, limit=1000,
                             batch_size=100) -> LocalSaleResult:
    period = supply_period_for_days(horizon_days)
    if period is None:
        raise ValueError("unsupported Ozon supply period")
    if period_from > period_to or not 1 <= limit <= 1000 or not 1 <= batch_size <= 100:
        raise ValueError("invalid local-sale request")
    catalog_skus = tuple(dict.fromkeys(parse_sku(sku) for sku in skus))
    by_id = {}
    for cluster in clusters:
        cluster_id = positive_int(cluster.cluster_id, "macrolocal cluster")
        if cluster_id in by_id or cluster.name in by_id.values():
            raise ValueError("ambiguous macrolocal cluster")
        by_id[cluster_id] = cluster.name
    known = set(catalog_skus)
    values = {}
    for start in range(0, len(catalog_skus), batch_size):
        batch = catalog_skus[start:start + batch_size]
        offset = 0
        while True:
            response = client.post_json(LOCAL_SALE_ITEMS_CLUSTERS_PATH, {
                "filter": {"delivery_schema": "FBO", "skus": list(batch),
                           "period": {"from": period_from.isoformat(), "to": period_to.isoformat()},
                           "supply_period": period},
                "limit": limit, "offset": offset,
            }, policy=READ)
            payload = response.get("result", response)
            if not isinstance(payload, dict):
                raise LocalSaleResponseShapeError(
                    f"result: {_json_kind(payload)}")
            items, total = payload.get("items"), payload.get("total")
            if not isinstance(items, list) or type(total) is not int or total < 0:
                raise LocalSaleResponseShapeError(
                    f"items: {_json_kind(payload.get('items', _MISSING))}; "
                    f"total: {_json_kind(payload.get('total', _MISSING))}; "
                    f"data: {_json_kind(payload.get('data', _MISSING))}")
            if offset + len(items) > total or len(items) > limit or not items and offset < total:
                raise ValueError("incomplete local-sale page")
            for raw in items:
                if not isinstance(raw, dict):
                    raise ValueError("invalid local-sale item")
                sku = parse_sku(raw.get("sku"))
                cluster_id = positive_int(raw.get("macrolocal_cluster_to_id"), "destination cluster")
                if sku not in known or sku not in batch or cluster_id not in by_id:
                    raise LocalSaleIdentityError(
                        _identity_disagreement(sku, cluster_id, known, batch, by_id))
                metrics = raw.get("metrics")
                if not isinstance(metrics, dict):
                    raise ValueError("invalid local-sale metrics")
                quantity = metrics.get("recommended_supply")
                if quantity is None:
                    continue
                quantity = nonnegative_int(quantity, "recommended_supply")
                key = (sku, by_id[cluster_id])
                if key in values and values[key] != quantity:
                    raise ValueError("conflicting local-sale recommendations")
                values[key] = quantity
            offset += len(items)
            if offset == total:
                break
    return LocalSaleResult(tuple(RecommendedSupply(sku, cluster, qty)
                                 for (sku, cluster), qty in sorted(values.items())),
                           datetime.now(timezone.utc).isoformat(), period_from,
                           period_to, horizon_days, period)
