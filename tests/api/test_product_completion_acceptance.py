"""Cross-layer acceptance for the final Product Completion presentation."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests.helpers.xlsx_fixtures import make_xlsx

ROOT = Path(__file__).parents[2]


def _build_product_completion_acceptance_files():
    """Deterministic, non-trivial upload set used by final cross-layer checks."""
    from tests.api.test_analysis import AVAILABILITY_HEADERS, PRODUCT_HEADERS, TARIFF_HEADERS

    availability_headers = AVAILABILITY_HEADERS + ["Артикул", "Название товара"]
    availability_rows = [
        ["SKU-1", "M1", "Москва", 999, 5, 0, 0, "39439", "Коллекторная группа"],
        ["SKU-1", "S1", "Самара", 999, 12, 0, 0, "39439", "Коллекторная группа"],
        ["SKU-2", "M2", "Москва", 999, 4, 0, 0, "ART-2", "Кран шаровой RTP"],
    ]
    restrictions = ("SKU;Склад;Статус;Причина\n"
                    "SKU-1;M1;Разрешено;\nSKU-1;S1;Разрешено;\n"
                    "SKU-2;M2;Разрешено;\n")
    header = ("SKU;Артикул;Количество;Цена продавца;Кластер отгрузки;"
              "Кластер доставки;Статус;Принят в обработку;Имя покупателя;"
              "Телефон;Email;Адрес\n")
    rows = []
    def order(sku, article, date, origin, destination, quantity, price):
        rows.append(f"{sku};{article};{quantity};{price};{origin};{destination};"
                    f"Доставлен;{date}T10:00:00;PII_BUYER_12345;"
                    "PII_PHONE_12345;PII_EMAIL_12345;PII_ADDRESS_12345")
    # W33 -> W34 is the canonical stockout/substitution shape for Moscow demand.
    for date in ("2026-06-29", "2026-07-06", "2026-07-13",
                 "2026-07-20", "2026-07-27", "2026-08-03"):
        order("SKU-1", "39439", date, "Москва", "Москва", 100, 1000)
    for origin, qty in (("Москва", 90), ("Казань", 5), ("Самара", 5)):
        order("SKU-1", "39439", "2026-08-10", origin, "Москва", qty, 1000)
    for origin, qty in (("Москва", 19), ("Казань", 62), ("Самара", 14)):
        order("SKU-1", "39439", "2026-08-17", origin, "Москва", qty, 1000)
    order("SKU-1", "39439", "2026-08-10", "Казань", "Самара", 30, 1000)
    order("SKU-1", "39439", "2026-08-17", "Казань", "Самара", 30, 1000)
    order("SKU-2", "ART-2", "2026-08-10", "Москва", "Москва", 20, 1200)
    order("SKU-2", "ART-2", "2026-08-17", "Москва", "Москва", 20, 1200)
    tariff_rows = [
        ["Москва", "Москва", 0, "", "", "", 40],
        ["Казань", "Москва", 0, "", "", "", 140],
        ["Казань", "Самара", 0, "", "", "", 80],
        ["Самара", "Самара", 0, "", "", "", 50],
        # Самара -> Москва is deliberately absent: its economics must fail closed.
    ]
    return {
        "availability_file": ("availability.xlsx", make_xlsx(headers=availability_headers, rows=availability_rows)),
        "restrictions_file": ("restrictions.csv", restrictions.encode()),
        "orders_file": ("orders.csv", (header + "\n".join(rows) + "\n").encode()),
        "tariffs_file": ("tariffs.xlsx", make_xlsx(headers=TARIFF_HEADERS, rows=tariff_rows)),
        "product_economics_file": ("products.xlsx", make_xlsx(headers=PRODUCT_HEADERS, rows=[
            ["SKU-1", "39439", 100, 20, 1000, "10%", 1],
            ["SKU-2", "ART-2", 200, 8, 1200, "10%", 1],
        ])),
    }


@pytest.fixture(scope="module")
def product_completion_payload():
    from tests.api.test_analysis import _analysis_data, _post_analysis
    response = _post_analysis(files=_build_product_completion_acceptance_files(),
                              data=_analysis_data())
    assert response.status_code == 200, response.text
    return response.json()


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


def _view(snapshot, source, mode, key):
    return next(view for view in snapshot["flow_view_aggregates"][source]
                if view["mode"] == mode and view["key"] == key)


def _route(view, origin, destination):
    return next(link for link in view["links"]
                if (link["origin_cluster_id"], link["destination_cluster_id"])
                == (origin, destination))


def test_product_completion_end_to_end_reconciles_snapshot(product_completion_payload):
    """Exercise uploads -> application orchestration -> serialized snapshot."""
    snapshot = product_completion_payload["snapshot"]
    assert snapshot["scenario"]["objective"] == "max_margin"
    assert {row["sku"] for row in snapshot["decision_rows"]} == {"SKU-1", "SKU-2"}
    demand = next(item for item in snapshot["demand_estimates"]
                  if item["sku"] == "SKU-1" and item["destination_cluster_id"] == "Москва")
    assert all(demand[name] is not None for name in
               ("m1", "m2", "latest_week_qty", "current_weekly_rate"))
    need = next(row["need"] for row in snapshot["decision_rows"]
                if row["sku"] == "SKU-1" and row["destination_cluster_id"] == "Москва")
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
            if link["quantity"]:
                assert sum(Decimal(item["route_share"])
                           for item in link["sku_breakdown"]) == Decimal(1)
        if view["mode"] == "destination" and view["total_quantity"]:
            assert sum(Decimal(link["destination_share"])
                       for link in view["links"]) == Decimal(1)
    assert snapshot["summary"]["total_safe_plan_qty"] == sum(
        row["safe_plan_qty"] for row in snapshot["decision_rows"]
        if row["safe_plan_qty"] is not None)


def test_product_completion_cleaning_changes_fulfillment_not_demand(product_completion_payload):
    snapshot = product_completion_payload["snapshot"]
    observed = _view(snapshot, "observed_views", "destination", "Москва")
    clean = _view(snapshot, "clean_views", "destination", "Москва")
    observed_route = _route(observed, "Казань", "Москва")
    clean_route = _route(clean, "Казань", "Москва")
    assert (observed["total_quantity"], clean["total_quantity"]) == (835, 740)
    assert (observed_route["quantity"], clean_route["quantity"]) == (67, 5)
    assert observed_route["origin_cluster_id"] == clean_route["origin_cluster_id"] == "Казань"
    assert observed_route["destination_cluster_id"] == clean_route["destination_cluster_id"] == "Москва"
    assert any(row["sku"] == "SKU-1" and row["destination_cluster_id"] == "Москва"
               for row in snapshot["demand_estimates"])


def test_product_completion_flow_economics_reconcile(product_completion_payload):
    snapshot = product_completion_payload["snapshot"]
    observed = _route(_view(snapshot, "observed_views", "destination", "Москва"),
                      "Казань", "Москва")
    clean = _route(_view(snapshot, "clean_views", "destination", "Москва"),
                   "Казань", "Москва")
    expected = {
        "route_cost_rub_per_unit": "140", "route_cost_pct_of_realization": "0.14",
        "current_margin_rate": "0.58", "local_route_cost_rub_per_unit": "40",
        "local_route_cost_pct_of_realization": "0.04", "local_margin_rate": "0.68",
        "margin_delta_pp": "10", "profit_delta_per_unit": "100",
    }
    assert {name: observed["economics"][name] for name in expected} == expected
    assert observed["economics"]["profit_opportunity_rub"] == "6700"
    assert clean["economics"]["profit_opportunity_rub"] == "500"
    assert observed["observed_profit_opportunity_rub"] == "6700"
    assert clean["observed_profit_opportunity_rub"] == "6700"
    incomplete = _route(_view(snapshot, "observed_views", "destination", "Москва"),
                        "Самара", "Москва")["economics"]
    assert incomplete["complete"] is False
    assert "CURRENT_ROUTE_INCOMPLETE" in incomplete["reason_codes"]
    for name in ("route_cost_rub_per_unit", "route_cost_pct_of_realization",
                 "current_margin_rate", "margin_delta_pp", "profit_opportunity_rub"):
        assert incomplete[name] is None


def test_product_completion_safe_and_calculated_semantics(product_completion_payload):
    rows = product_completion_payload["snapshot"]["decision_rows"]
    row = next(row for row in rows if row["sku"] == "SKU-1"
               and row["destination_cluster_id"] == "Москва")
    assert row["need"]["ozon_recommended_qty"] == 5
    assert row["need"]["calculated_need_qty"] > 5
    assert row["safe_plan_qty"] == 5
    assert row["calculated_plan_qty"] > row["safe_plan_qty"]


def test_product_completion_rejects_max_volume():
    from tests.api.test_analysis import _analysis_data, _post_analysis
    response = _post_analysis(files=_build_product_completion_acceptance_files(),
                              data=_analysis_data(optimization_objective="max_volume"))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OPTIMIZATION_OBJECTIVE"


def test_product_completion_max_margin_prioritizes_more_profitable_margin_route():
    from tests.api.test_analysis import (AVAILABILITY_HEADERS, TARIFF_HEADERS,
                                         _analysis_data, _analysis_files,
                                         _orders, _post_analysis)

    files = _analysis_files(available_stock=4)
    files["availability_file"] = (
        "availability.xlsx",
        make_xlsx(headers=AVAILABILITY_HEADERS, rows=[
            ["SKU-1", "W1", "Москва", 999, 10, 0, 0],
            ["SKU-1", "W2", "Уфа", 999, 10, 0, 0],
        ]),
    )
    files["restrictions_file"] = (
        "restrictions.csv",
        "SKU;Склад;Статус;Причина\nSKU-1;W1;Разрешено;\nSKU-1;W2;Разрешено;\n".encode(),
    )
    files["orders_file"] = (
        "orders.csv",
        _orders(destination="Москва") + _orders(destination="Уфа").split(b"\n", 1)[1],
    )
    files["tariffs_file"] = (
        "tariffs.xlsx",
        make_xlsx(headers=TARIFF_HEADERS, rows=[
            [origin, destination, 0, "", "", "", 40 if origin == "Москва" else 100]
            for origin in ("Москва", "Уфа")
            for destination in ("Москва", "Уфа")
        ]),
    )
    response = _post_analysis(files=files, data=_analysis_data())
    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    rows = {row["destination_cluster_id"]: row for row in snapshot["decision_rows"]}
    margins = {item["placement_cluster_id"]: Decimal(item["margin_rate"])
               for item in snapshot["unit_economics"] if item["sku"] == "SKU-1"}
    assert margins["Москва"] > margins["Уфа"]
    assert rows["Москва"]["calculated_plan_qty"] == 4
    assert rows["Уфа"]["calculated_plan_qty"] == 0
    assert sum(row["calculated_plan_qty"] for row in rows.values()) == 4

def test_product_completion_rejects_legacy_max_profit():
    from tests.api.test_analysis import _analysis_data, _post_analysis
    response = _post_analysis(files=_build_product_completion_acceptance_files(),
                              data=_analysis_data(optimization_objective="max_profit"))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OPTIMIZATION_OBJECTIVE"

def test_product_completion_snapshot_excludes_buyer_pii(product_completion_payload):
    serialized = json.dumps(product_completion_payload["snapshot"], ensure_ascii=False)
    for marker in ("PII_BUYER_12345", "PII_PHONE_12345", "PII_EMAIL_12345",
                   "PII_ADDRESS_12345"):
        assert marker not in serialized


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
