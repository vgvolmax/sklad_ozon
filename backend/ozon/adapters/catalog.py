"""Canonical macro-cluster catalog and warehouse-to-macro mapping."""

from dataclasses import dataclass
from backend.domain.contracts import ImportDiagnostic
from backend.ozon.adapters.wire import optional_text, positive_int
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import CLUSTERS_V1_PATH, CLUSTERS_V2_PATH, SELLER_WAREHOUSES_PATH
from backend.ozon.source_contracts import Cluster, SellerWarehouse

READ = OzonRequestPolicy(retry_safe=True)
V1_CLUSTER_REQUEST = {"cluster_type": "CLUSTER_TYPE_OZON"}


def _collection(response: dict, key: str) -> list:
    if key in response:
        value = response[key]
    else:
        result = response.get("result")
        if isinstance(result, dict) and key in result:
            value = result[key]
        elif key == "clusters" and isinstance(result, list):
            value = result
        else:
            raise ValueError(f"missing {key} collection")
    if not isinstance(value, list):
        raise ValueError(f"invalid {key} collection")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"invalid {key} item")
    return value


def _v2_cluster(raw: dict) -> Cluster:
    cluster_id = positive_int(raw.get("macrolocal_cluster_id"), "cluster ID")
    data = raw.get("data")
    if not isinstance(data, dict): raise ValueError("invalid cluster data")
    macro = data.get("macrolocal_cluster")
    if not isinstance(macro, dict): raise ValueError("invalid macrolocal cluster")
    name = macro.get("name")
    if not isinstance(name, str) or not name.strip(): raise ValueError("invalid cluster name")
    return Cluster(cluster_id, name.strip())


@dataclass(frozen=True, slots=True)
class ClusterCatalogResult:
    clusters: tuple[Cluster, ...]
    warehouse_to_macrolocal: dict[int, int]
    diagnostics: tuple[ImportDiagnostic, ...]


def normalize_clusters(v2_response: dict, v1_response: dict | None = None) -> ClusterCatalogResult:
    by_id, conflicted, diagnostics = {}, set(), []
    for raw in _collection(v2_response, "clusters"):
        cluster = _v2_cluster(raw)
        previous = by_id.get(cluster.cluster_id)
        if previous is not None and previous != cluster:
            conflicted.add(cluster.cluster_id)
            diagnostics.append(ImportDiagnostic("error", "CONFLICTING_CLUSTER_ID", f"Conflicting Ozon cluster ID {cluster.cluster_id}."))
        elif cluster.cluster_id not in conflicted:
            by_id[cluster.cluster_id] = cluster
    for cid in conflicted: by_id.pop(cid, None)
    warehouse_to_macro, conflicted_warehouses = {}, set()
    if v1_response is not None:
        for raw in _collection(v1_response, "clusters"):
            macro_id = positive_int(raw.get("macrolocal_cluster_id"), "macrolocal cluster ID")
            logistics = raw.get("logistic_clusters", [])
            if not isinstance(logistics, list): raise ValueError("invalid logistic_clusters")
            for logistic in logistics:
                if not isinstance(logistic, dict): raise ValueError("invalid logistic cluster")
                warehouses = logistic.get("warehouses", [])
                if not isinstance(warehouses, list): raise ValueError("invalid warehouses")
                for warehouse in warehouses:
                    if not isinstance(warehouse, dict): raise ValueError("invalid warehouse mapping")
                    wid = positive_int(warehouse.get("warehouse_id"), "warehouse ID")
                    if wid in conflicted_warehouses: continue
                    previous = warehouse_to_macro.get(wid)
                    if previous is not None and previous != macro_id:
                        diagnostics.append(ImportDiagnostic("error", "CONFLICTING_WAREHOUSE_CLUSTER", f"Conflicting cluster for warehouse {wid}."))
                        warehouse_to_macro.pop(wid, None); conflicted_warehouses.add(wid)
                    elif previous is None: warehouse_to_macro[wid] = macro_id
    return ClusterCatalogResult(tuple(by_id[k] for k in sorted(by_id)), warehouse_to_macro, tuple(diagnostics))


def normalize_seller_warehouses(response: dict):
    by_id, conflicted, diagnostics = {}, set(), []
    for raw in _collection(response, "warehouses"):
        wid = positive_int(raw.get("warehouse_id"), "seller warehouse ID")
        active = raw.get("is_active")
        if not isinstance(active, bool): raise ValueError("invalid seller warehouse active flag")
        pickup = raw.get("is_pickup")
        if pickup is not None and not isinstance(pickup, bool): raise ValueError("invalid seller warehouse pickup flag")
        warehouse = SellerWarehouse(wid, optional_text(raw.get("name"), "warehouse name"),
                                    optional_text(raw.get("address"), "warehouse address"), active, pickup)
        previous = by_id.get(wid)
        if previous is not None and previous != warehouse:
            conflicted.add(wid)
            diagnostics.append(ImportDiagnostic("error", "CONFLICTING_SELLER_WAREHOUSE_ID", f"Conflicting seller warehouse ID {wid}."))
        elif wid not in conflicted: by_id[wid] = warehouse
    for wid in conflicted: by_id.pop(wid, None)
    return tuple(by_id[k] for k in sorted(by_id)), tuple(diagnostics)


def fetch_clusters(client):
    return normalize_clusters(client.post_json(CLUSTERS_V2_PATH, {}, policy=READ),
                              client.post_json(CLUSTERS_V1_PATH, V1_CLUSTER_REQUEST, policy=READ))


def fetch_seller_warehouses(client):
    return normalize_seller_warehouses(client.post_json(SELLER_WAREHOUSES_PATH, {}, policy=READ))
