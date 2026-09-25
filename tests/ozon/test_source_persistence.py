import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle, OrderRecord
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.adapters.product_facts import ProductApiFacts
from backend.ozon.adapters.local_sale import LocalSaleResult, RecommendedSupply
from backend.ozon.source_contracts import (
    Cluster, EndpointEvidence, OzonApiErrorEvidence, OzonRecordQualityEvidence,
    OzonSourceSnapshot, PlacementZoneEvidence, SellerWarehouse,
)
from backend.ozon.source_persistence import (
    load_source_snapshot_if_exists, save_source_snapshot_atomic,
    source_snapshot_from_document, source_snapshot_to_document,
)


def snapshot(identity="source-a"):
    diagnostic = ImportDiagnostic("warning", "TEST", "Normalized evidence")
    quality = OzonRecordQualityEvidence(1, ("sku-1",))
    error = OzonApiErrorEvidence("OZON_RATE_LIMITED", "/endpoint", 429,
                                 "RATE", "Later", "request-1", "http", 2, 30)
    return OzonSourceSnapshot(
        identity, "2026-09-22T08:00:00+00:00", date(2026, 9, 22), "UTC+03:00",
        date(2026, 6, 1), date(2026, 9, 22),
        (OrderRecord("sku-1", 2, "origin", "destination", OrderLifecycle.FULFILLED,
                     "2026-09-20T10:00:00+03:00", source_channel="fbo"),),
        (AvailabilityRecord("sku-1", "warehouse", "cluster", 4.0),),
        (AvailabilityRecord("sku-1", "seller", "", 7.0),),
        (Cluster(1, "cluster"),),
        (SellerWarehouse(2, "seller", None, True, False),),
        (PlacementZoneEvidence("sku-1", ("zone-a",)),),
        (EndpointEvidence("orders_fbo", "2026-09-22T07:00:00+00:00", 1, False,
                          (diagnostic,), error, quality),),
        (diagnostic,), "credential-a",
        (ProductApiFacts("sku-1", "article-1", 3, Decimal("10.50"),
                         Decimal("0.15"), Decimal("1.25")),),
        ((777, 10), (888, 20)),
    )


def test_source_snapshot_round_trip_restores_domain_types(tmp_path):
    path = tmp_path / "source.json"
    original = snapshot()
    save_source_snapshot_atomic(path, original)
    assert load_source_snapshot_if_exists(path) == original


def test_source_snapshot_round_trip_preserves_exact_56_day_recommendations(tmp_path):
    path = tmp_path / "source.json"
    original = replace(snapshot(), recommended_supply=LocalSaleResult(
        (RecommendedSupply("sku-1", "cluster", 0),),
        "2026-09-22T08:00:00+00:00", date(2026, 6, 1), date(2026, 9, 22),
        56, "EIGHT_WEEKS"))
    save_source_snapshot_atomic(path, original)
    assert load_source_snapshot_if_exists(path).recommended_supply == original.recommended_supply


def test_partial_recommendation_quality_survives_restart(tmp_path):
    path = tmp_path / 'source.json'
    original = replace(snapshot(), recommended_supply=LocalSaleResult(
        (RecommendedSupply('sku-2', 'cluster', 0),),
        '2026-09-22T08:00:00+00:00', date(2026, 6, 1), date(2026, 9, 22),
        56, 'EIGHT_WEEKS', excluded_record_count=1,
        incomplete_skus=('sku-1',), unknown_cluster_ids=(4042,)))
    save_source_snapshot_atomic(path, original)
    assert load_source_snapshot_if_exists(path).recommended_supply == original.recommended_supply


def test_partial_recommendation_cannot_restore_value_for_affected_sku():
    document = source_snapshot_to_document(replace(snapshot(),
        recommended_supply=LocalSaleResult(
            (RecommendedSupply('sku-1', 'cluster', 2),),
            '2026-09-22T08:00:00+00:00', date(2026, 6, 1), date(2026, 9, 22),
            56, 'EIGHT_WEEKS', excluded_record_count=1,
            incomplete_skus=('sku-1',), unknown_cluster_ids=(4042,))))
    with pytest.raises(ValueError, match='invalid recommendation coverage'):
        source_snapshot_from_document(document)


def test_previous_source_snapshot_without_recommendation_still_loads():
    document = source_snapshot_to_document(snapshot())
    document["snapshot"].pop("recommended_supply", None)
    assert source_snapshot_from_document(document).recommended_supply is None


@pytest.mark.parametrize("mutation", [
    lambda document: "{broken",
    lambda document: {**document, "schema_version": 99},
    lambda document: {**document, "schema_version": 1},
    lambda document: ({**document, "snapshot": {**document["snapshot"],
        "product_facts": [{**document["snapshot"]["product_facts"][0], "price": "wrong"}]}}),
    lambda document: ({**document, "snapshot": {**document["snapshot"],
        "orders": [{**document["snapshot"]["orders"][0], "lifecycle": "wrong"}]}}),
    lambda document: ({**document, "snapshot": {key: value for key, value in document["snapshot"].items()
                                                  if key != "source_snapshot_id"}}),
])
def test_corrupt_documents_are_rejected(tmp_path, mutation):
    path = tmp_path / "source.json"
    document = source_snapshot_to_document(snapshot())
    value = mutation(document)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    with pytest.raises((ValueError, json.JSONDecodeError)):
        load_source_snapshot_if_exists(path)


def test_replace_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "source.json"
    original = snapshot()
    save_source_snapshot_atomic(path, original)
    monkeypatch.setattr("backend.ozon.source_persistence.os.replace",
                        lambda *_args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        save_source_snapshot_atomic(path, replace(original, source_snapshot_id="source-b"))
    assert source_snapshot_from_document(json.loads(path.read_text(encoding="utf-8"))) == original


@pytest.mark.parametrize("mapping", [
    [[-1, 10]],
    [[777, 0]],
    [[777, 10], [777, 20]],
    [[777]],
    [["777", 10]],
    [[True, 10]],
])
def test_corrupt_warehouse_mapping_is_rejected(mapping):
    document = source_snapshot_to_document(snapshot())
    document["snapshot"]["warehouse_to_macrolocal"] = mapping

    with pytest.raises(ValueError):
        source_snapshot_from_document(document)
