from tests.helpers.xlsx_fixtures import make_xlsx


def _files(*, include_unrelated_sku_orders: bool):
    from tests.api.test_analysis import AVAILABILITY_HEADERS, PRODUCT_HEADERS, TARIFF_HEADERS

    header = (
        "SKU;Артикул;Количество;Цена продавца;Кластер отгрузки;"
        "Кластер доставки;Статус;Принят в обработку\n"
    )
    rows = [
        "SKU-A;A;10;1000;Москва;Москва;Доставлен;2026-07-27T10:00:00",
        "SKU-A;A;10;1000;Москва;Москва;Доставлен;2026-08-17T10:00:00",
    ]
    if include_unrelated_sku_orders:
        rows.extend((
            "SKU-B;B;100;1000;Москва;Москва;Доставлен;2026-08-03T10:00:00",
            "SKU-B;B;100;1000;Москва;Москва;Доставлен;2026-08-10T10:00:00",
        ))

    return {
        "availability_file": (
            "availability.xlsx",
            make_xlsx(
                headers=AVAILABILITY_HEADERS,
                rows=[
                    ["SKU-A", "W-A", "Москва", 100, 0, 0, 0],
                    ["SKU-B", "W-B", "Москва", 100, 0, 0, 0],
                ],
            ),
        ),
        "restrictions_file": (
            "restrictions.csv",
            (
                "SKU;Склад;Статус;Причина\n"
                "SKU-A;W-A;Разрешено;\n"
                "SKU-B;W-B;Разрешено;\n"
            ).encode(),
        ),
        "orders_file": (
            "orders.csv",
            (header + "\n".join(rows) + "\n").encode(),
        ),
        "tariffs_file": (
            "tariffs.xlsx",
            make_xlsx(headers=TARIFF_HEADERS, rows=[["Москва", "Москва", 0, "", "", "", 40]]),
        ),
        "product_economics_file": (
            "products.xlsx",
            make_xlsx(
                headers=PRODUCT_HEADERS,
                rows=[
                    ["SKU-A", "A", 100, 20, 1000, "10%", 1],
                    ["SKU-B", "B", 100, 20, 1000, "10%", 1],
                ],
            ),
        ),
    }


def _snapshot(*, include_unrelated_sku_orders: bool):
    from tests.api.test_analysis import _analysis_data, _post_analysis

    response = _post_analysis(
        files=_files(include_unrelated_sku_orders=include_unrelated_sku_orders),
        data=_analysis_data(),
    )
    assert response.status_code == 200, response.text
    return response.json()["snapshot"]


def _sku_a_view(snapshot):
    demand = next(
        item
        for item in snapshot["demand_estimates"]
        if item["sku"] == "SKU-A" and item["destination_cluster_id"] == "Москва"
    )
    decision = next(
        item
        for item in snapshot["decision_rows"]
        if item["sku"] == "SKU-A" and item["destination_cluster_id"] == "Москва"
    )
    return demand, decision["need"]


def test_unrelated_sku_orders_do_not_change_existing_sku_demand_or_need():
    baseline = _snapshot(include_unrelated_sku_orders=False)
    variant = _snapshot(include_unrelated_sku_orders=True)

    baseline_demand, baseline_need = _sku_a_view(baseline)
    variant_demand, variant_need = _sku_a_view(variant)

    assert baseline_demand == variant_demand
    assert baseline_need == variant_need
    assert baseline_demand["eligible_week_count"] == 4
