import json
from dataclasses import replace
from decimal import Decimal

import pytest

from backend.domain.contracts import ProductEconomicsInput, ReportMeta, TariffRow
from backend.project import (
    EconomicsSettings, OperationalSnapshot, OptimizerThresholds, Project,
    ProjectValidationError, load_project, save_project_atomic,
)


def sample_project() -> Project:
    meta = ReportMeta("safe.xlsx", "2026-08-24T10:00:00Z", report_generated_at="2026-08-23")
    return Project(
        tariffs=(TariffRow("Kazan", "Moscow", Decimal("0"), Decimal("2.5"), None, Decimal("635.770"), Decimal("49.90")),),
        tariff_meta=meta,
        product_economics=(ProductEconomicsInput("100", "ART", Decimal("635.770"), 12, Decimal("999.5"), Decimal("0.41"), Decimal("2.5")),),
        product_economics_meta=meta,
        seller_available_stock={"100": 12},
        manual_cluster_mappings={"  мск ": "Moscow"},
        economics_settings=EconomicsSettings(Decimal("0.01"), Decimal("0.05"), Decimal("0.9"), Decimal("30"), "usn_income", Decimal("0.06"), Decimal("0"), Decimal("0.1")),
        optimizer_thresholds=OptimizerThresholds(Decimal("100"), Decimal("0.1"), Decimal("0.2")),
        operational_snapshots=(OperationalSnapshot("availability", report_date="2026-08-23", records=({"sku": "100", "warehouse": "W", "cluster": "Moscow", "available_quantity": "4"},)),),
    )


def test_valid_project_round_trip_preserves_all_inputs_and_decimal_strings(tmp_path):
    path = tmp_path / "project.json"
    project = sample_project()
    save_project_atomic(path, project)
    payload = json.loads(path.read_text("utf-8"))
    assert payload["schema_version"] == 1
    assert payload["tariffs"][0]["max_price"] == "635.77"
    assert payload["product_economics"][0]["cost"] == "635.77"
    assert load_project(path) == replace(project, tariffs=(replace(project.tariffs[0], max_price=Decimal("635.77"), logistics_fee=Decimal("49.9")),), product_economics=(replace(project.product_economics[0], cost=Decimal("635.77")),))


@pytest.mark.parametrize("mutation", [
    lambda p: p.pop("schema_version"),
    lambda p: p.update(schema_version=2),
    lambda p: p.update(unknown=True),
])
def test_rejects_missing_future_version_and_unknown_top_level_fields(tmp_path, mutation):
    path = tmp_path / "project.json"
    save_project_atomic(path, sample_project())
    payload = json.loads(path.read_text("utf-8")); mutation(payload)
    path.write_text(json.dumps(payload), "utf-8")
    with pytest.raises(ProjectValidationError): load_project(path)


def test_rejects_undated_snapshot_before_touching_existing_target(tmp_path):
    path = tmp_path / "project.json"; save_project_atomic(path, sample_project()); old = path.read_bytes()
    invalid = replace(sample_project(), operational_snapshots=(OperationalSnapshot("orders", records=()),))
    with pytest.raises(ProjectValidationError): save_project_atomic(path, invalid)
    assert path.read_bytes() == old


def test_save_rejects_nested_pii_and_malformed_snapshot_before_writing(tmp_path):
    path = tmp_path / "project.json"
    nested = replace(sample_project(), operational_snapshots=(OperationalSnapshot("availability", report_date="2026-08-23", records=({"sku": {"buyer_name": "secret"}, "warehouse": "W", "cluster": "C", "available_quantity": 1},)),))
    with pytest.raises(ProjectValidationError): save_project_atomic(path, nested)
    assert not path.exists()


@pytest.mark.parametrize("forbidden", ["buyer_name", "customer_name", "address", "phone", "email", "inn", "kpp", "raw_row", "raw_report", "raw_bytes", "raw_csv", "raw_xlsx", "base64_report", "payment_data"])
def test_persistence_defensively_rejects_pii_and_raw_report_fields(tmp_path, forbidden):
    path = tmp_path / "project.json"; save_project_atomic(path, sample_project())
    payload = json.loads(path.read_text("utf-8")); payload["operational_snapshots"][0]["records"][0][forbidden] = "synthetic-secret"
    path.write_text(json.dumps(payload), "utf-8")
    with pytest.raises(ProjectValidationError): load_project(path)


def test_replace_failure_preserves_old_target_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "project.json"; save_project_atomic(path, sample_project()); old = path.read_bytes()
    def fail_replace(source, target): raise OSError("synthetic replace failure")
    monkeypatch.setattr("backend.project.os.replace", fail_replace)
    with pytest.raises(OSError, match="synthetic"):
        save_project_atomic(path, replace(sample_project(), seller_available_stock={"100": 5}))
    assert path.read_bytes() == old
    assert list(tmp_path.iterdir()) == [path]
