"""Cross-layer acceptance for the final Product Completion presentation."""
import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_product_frontend_consumes_snapshot_without_business_calculators_or_pii():
    sources = "\n".join((ROOT / "frontend/assets/js" / name).read_text()
                        for name in ("core.js", "components.js", "flow.js", "app.js"))
    assert "result.snapshot" in sources
    for legacy in ("data.placements", "data.allocations", "data.safe_allocations",
                   "data.logistics", "data.economics"):
        assert legacy not in sources
    for calculator in ("calculateNeed", "calculateMargin", "calculateRouteEconomics",
                       "allocateStock", "forecastDemand"):
        assert calculator not in sources


def test_product_completion_end_to_end_reconciles_snapshot():
    """Exercise uploads -> application orchestration -> serialized snapshot."""
    from tests.api.test_analysis import (_analysis_data, _analysis_files,
                                          _post_analysis,
                                          _two_sku_analysis_files)

    files = _two_sku_analysis_files()
    header = ("SKU;Количество;Цена продавца;Кластер отгрузки;"
              "Кластер доставки;Статус;Принят в обработку\n")
    rows = [f"{sku};1;1000;Москва;Москва;Доставлен;{date}T10:00:00"
            for date in ("2026-07-01", "2026-07-08", "2026-07-15", "2026-07-22",
                         "2026-07-29", "2026-08-05", "2026-08-12", "2026-08-19")
            for sku in ("SKU-1", "SKU-2")]
    files["orders_file"] = ("orders.csv", (header + "\n".join(rows) + "\n").encode())
    response = _post_analysis(files=files, data=_analysis_data())
    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert {row["sku"] for row in snapshot["decision_rows"]} == {"SKU-1", "SKU-2"}
    demand = snapshot["demand_estimates"][0]
    assert all(demand[name] is not None for name in
               ("m1", "m2", "latest_week_qty", "current_weekly_rate"))
    need = snapshot["decision_rows"][0]["need"]
    assert need["calculated_need_qty"] is not None
    assert need["horizon_days"] == 56
    assert need["ozon_recommended_qty"] is not None
    assert snapshot["summary"]["total_calculated_plan_qty"] == sum(
        row["calculated_plan_qty"] for row in snapshot["decision_rows"]
        if row["calculated_plan_qty"] is not None)
    for view in (*snapshot["flow_view_aggregates"]["observed_views"],
                 *snapshot["flow_view_aggregates"]["clean_views"]):
        assert sum(link["quantity"] for link in view["links"]) == view["total_quantity"]
        for link in view["links"]:
            assert sum(item["quantity"] for item in link["sku_breakdown"]) == link["quantity"]

    pii_response = _post_analysis(files=_analysis_files(pii=True), data=_analysis_data())
    serialized = json.dumps(pii_response.json()["snapshot"]).lower()
    assert not any(marker.lower() in serialized for marker in
                   ("PII_BUYER_12345", "PII_PHONE_12345", "PII_EMAIL_12345",
                    "PII_ADDRESS_12345"))


def test_all_runtime_assets_are_part_of_shell_ci_and_windows_acceptance():
    html = (ROOT / "frontend/index.html").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    windows = (ROOT / "tests/windows/portable-smoke.ps1").read_text()
    assets = ("core.js", "components.js", "flow.js", "app.js")
    positions = [html.index(f'/assets/js/{name}') for name in assets]
    assert positions == sorted(positions)
    for name in assets:
        assert f"node --check frontend/assets/js/{name}" in ci
        assert f'/assets/js/{name}' in windows
