"""Repeatable local import benchmark; deliberately excluded from normal CI.

Run from the repository root with ``python scripts/benchmark_report_imports.py``.
The generated data is synthetic, sanitized, and shaped like operational reports.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.contracts import ReportMeta
from backend.ingestion.availability import import_availability
from backend.ingestion.orders import import_orders
from backend.ingestion.restrictions import import_restrictions
from backend.ingestion.unitka import import_unitka_bundle
from tests.helpers.xlsx_fixtures import make_real_unitka, make_xlsx


META = ReportMeta("synthetic-benchmark", datetime.now(timezone.utc).isoformat())


def measured(name, operation):
    started = perf_counter()
    result = operation()
    elapsed = perf_counter() - started
    print(f"{name}: {elapsed:.3f}s rows={len(result.records)}")
    return elapsed


def main():
    print("Generating sanitized fixtures (generation is not included in timings)...")
    availability = make_xlsx(
        headers=[None],
        rows=[[None]] * 4 + [["SKU", "Артикул", "Кластер", "Остаток FBO, шт", "Остаток FBS, шт", "Рекомендуемая поставка по FBO"]]
        + [[f"S{i}", f"A{i}", "Москва", 10, 2, 5] for i in range(10_000)],
    )
    restrictions = make_xlsx(
        headers=["SKU", "Кластер", "Склад", "Возможно ли поставить товар", "Максимальный размер поставки"],
        rows=[[f"S{i % 10_000}", "Москва", f"W{i % 20}", "Да", 100] for i in range(30_000)],
    )
    orders_header = "SKU;Артикул продавца;Количество;Ваша цена;Кластер отгрузки;Кластер доставки;Статус;Принят в обработку\n"
    orders = (orders_header + "".join(
        f"S{i % 10_000};A{i % 10_000};1;1000;Москва;Москва;Доставлен;2026-07-01T10:00:00\n"
        for i in range(100_000)
    )).encode()
    unitka = make_real_unitka(
        product_rows=[[f"A{i}", "Товар", 100, 1000, "10%", 1] for i in range(620)],
        tariff_rows=[(i / 10, f"{i / 10}-{(i + 1) / 10} л", "Москва", "Москва", 18, 69) for i in range(320)],
    )

    total_started = perf_counter()
    measured("availability", lambda: import_availability(availability, META))
    measured("restrictions", lambda: import_restrictions(restrictions, META))
    measured("orders", lambda: import_orders(orders, META))
    parts = {}
    bundle = import_unitka_bundle(
        unitka,
        META,
        timing=lambda name, elapsed, rows: parts.update({name: (elapsed, rows)}),
    )
    for name in ("unitka_open", "unitka_tariffs", "unitka_economics"):
        elapsed, rows = parts[name]
        suffix = "" if rows is None else f" rows={rows}"
        print(f"{name}: {elapsed:.3f}s{suffix}")
    assert bundle.tariffs.records and bundle.product_economics.records
    print(f"reports total: {perf_counter() - total_started:.3f}s")


if __name__ == "__main__":
    main()
