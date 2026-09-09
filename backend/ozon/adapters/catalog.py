"""Canonical Ozon-ID cluster and seller-warehouse catalogs."""

from backend.domain.contracts import ImportDiagnostic
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import CLUSTERS_V1_PATH, CLUSTERS_V2_PATH, SELLER_WAREHOUSES_PATH
from backend.ozon.source_contracts import Cluster, SellerWarehouse

READ = OzonRequestPolicy(retry_safe=True)
V1_CLUSTER_REQUEST = {"cluster_type": "CLUSTER_TYPE_OZON"}


def _list(response: dict, key: str) -> list:
    value = response.get(key)
    if isinstance(value, list):
        return value
    result = response.get("result")
    if isinstance(result, dict) and isinstance(result.get(key), list):
        return result[key]
    return result if isinstance(result, list) else []


def _v2_cluster(raw: dict) -> Cluster | None:
    data = raw.get("data")
    macro = data.get("macrolocal_cluster") if isinstance(data, dict) else None
    cluster_id = raw.get("macrolocal_cluster_id")
    name = macro.get("name") if isinstance(macro, dict) else None
    try:
        return Cluster(int(cluster_id), str(name).strip()) if str(name or "").strip() else None
    except (TypeError, ValueError):
        return None


def _v1_cluster(raw: dict) -> Cluster | None:
    try:
        cluster_id = int(raw["cluster_id"])
        name = str(raw["name"]).strip()
        return Cluster(cluster_id, name) if name else None
    except (KeyError, TypeError, ValueError):
        return None


def normalize_clusters(v2_response: dict, v1_response: dict | None = None):
    by_id: dict[int, Cluster] = {}
    conflicted: set[int] = set()
    diagnostics: list[ImportDiagnostic] = []
    candidates = [(_v2_cluster(raw), "v2") for raw in _list(v2_response, "clusters") if isinstance(raw, dict)]
    if v1_response is not None:
        candidates += [(_v1_cluster(raw), "v1") for raw in _list(v1_response, "clusters") if isinstance(raw, dict)]
    for cluster, _version in candidates:
        if cluster is None:
            diagnostics.append(ImportDiagnostic("error", "INVALID_CLUSTER", "Invalid canonical Ozon cluster evidence."))
            continue
        previous = by_id.get(cluster.cluster_id)
        if previous is not None and previous != cluster:
            conflicted.add(cluster.cluster_id)
            diagnostics.append(ImportDiagnostic(
                "error", "CONFLICTING_CLUSTER_ID",
                f"Conflicting Ozon cluster ID {cluster.cluster_id}."))
            continue
        by_id[cluster.cluster_id] = cluster
    for cluster_id in conflicted:
        by_id.pop(cluster_id, None)
    return tuple(by_id[key] for key in sorted(by_id)), tuple(diagnostics)


def normalize_seller_warehouses(response: dict):
    by_id: dict[int, SellerWarehouse] = {}
    conflicted: set[int] = set()
    diagnostics: list[ImportDiagnostic] = []
    for raw in _list(response, "warehouses"):
        if not isinstance(raw, dict):
            continue
        try:
            warehouse = SellerWarehouse(
                int(raw["warehouse_id"]),
                str(raw["name"]).strip() if raw.get("name") is not None else None,
                str(raw["address"]).strip() if raw.get("address") is not None else None,
                bool(raw.get("is_active")),
                bool(raw["is_pickup"]) if raw.get("is_pickup") is not None else None,
            )
        except (KeyError, TypeError, ValueError):
            diagnostics.append(ImportDiagnostic("error", "INVALID_SELLER_WAREHOUSE", "Invalid seller warehouse evidence."))
            continue
        previous = by_id.get(warehouse.seller_warehouse_id)
        if previous is not None and previous != warehouse:
            conflicted.add(warehouse.seller_warehouse_id)
            diagnostics.append(ImportDiagnostic("error", "CONFLICTING_SELLER_WAREHOUSE_ID",
                                                f"Conflicting seller warehouse ID {warehouse.seller_warehouse_id}."))
            continue
        by_id[warehouse.seller_warehouse_id] = warehouse
    for warehouse_id in conflicted:
        by_id.pop(warehouse_id, None)
    return tuple(by_id[key] for key in sorted(by_id)), tuple(diagnostics)


def fetch_clusters(client: OzonClient):
    v2 = client.post_json(CLUSTERS_V2_PATH, {}, policy=READ)
    v1 = client.post_json(CLUSTERS_V1_PATH, V1_CLUSTER_REQUEST, policy=READ)
    return normalize_clusters(v2, v1)


def fetch_seller_warehouses(client: OzonClient):
    return normalize_seller_warehouses(client.post_json(SELLER_WAREHOUSES_PATH, {}, policy=READ))
