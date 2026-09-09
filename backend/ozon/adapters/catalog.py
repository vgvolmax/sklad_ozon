"""Canonical Ozon cluster and seller-warehouse catalogs."""

from backend.domain.contracts import ImportDiagnostic
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import CLUSTERS_V1_PATH, CLUSTERS_V2_PATH, SELLER_WAREHOUSES_PATH
from backend.ozon.source_contracts import Cluster, SellerWarehouse

READ = OzonRequestPolicy(retry_safe=True)


def _items(response: dict, *keys: str) -> list:
    value = response.get("result", response)
    for key in keys:
        if isinstance(value, dict) and isinstance(value.get(key), list):
            return value[key]
    return value if isinstance(value, list) else []


def normalize_clusters(responses: tuple[dict, ...]) -> tuple[tuple[Cluster, ...], tuple[ImportDiagnostic, ...]]:
    by_id: dict[int, Cluster] = {}
    diagnostics = []
    for response in responses:
        for raw in _items(response, "clusters", "items"):
            try:
                cluster = Cluster(int(raw.get("id", raw.get("cluster_id"))), str(raw.get("name", "")).strip())
            except (TypeError, ValueError):
                continue
            previous = by_id.get(cluster.cluster_id)
            if previous is not None and previous != cluster:
                diagnostics.append(ImportDiagnostic("error", "CONFLICTING_CLUSTER_ID", f"Conflicting Ozon cluster ID {cluster.cluster_id}"))
                continue
            by_id[cluster.cluster_id] = cluster
    return tuple(by_id.values()), tuple(diagnostics)


def normalize_seller_warehouses(response: dict) -> tuple[tuple[SellerWarehouse, ...], tuple[ImportDiagnostic, ...]]:
    by_id = {}
    diagnostics = []
    for raw in _items(response, "warehouses", "items"):
        try:
            warehouse = SellerWarehouse(
                int(raw.get("warehouse_id", raw.get("id"))),
                str(raw.get("name")).strip() if raw.get("name") is not None else None,
                str(raw.get("address")).strip() if raw.get("address") is not None else None,
                bool(raw.get("is_active", raw.get("status") == "active")),
                bool(raw["is_pickup"]) if raw.get("is_pickup") is not None else None,
            )
        except (TypeError, ValueError):
            continue
        previous = by_id.get(warehouse.seller_warehouse_id)
        if previous is not None and previous != warehouse:
            diagnostics.append(ImportDiagnostic("error", "CONFLICTING_SELLER_WAREHOUSE_ID", f"Conflicting seller warehouse ID {warehouse.seller_warehouse_id}"))
            continue
        by_id[warehouse.seller_warehouse_id] = warehouse
    return tuple(by_id.values()), tuple(diagnostics)


def fetch_catalogs(client: OzonClient):
    clusters = tuple(client.post_json(path, {}, policy=READ) for path in (CLUSTERS_V2_PATH, CLUSTERS_V1_PATH))
    cluster_records, cluster_diagnostics = normalize_clusters(clusters)
    warehouses = client.post_json(SELLER_WAREHOUSES_PATH, {}, policy=READ)
    seller_records, seller_diagnostics = normalize_seller_warehouses(warehouses)
    return cluster_records, seller_records, cluster_diagnostics + seller_diagnostics
