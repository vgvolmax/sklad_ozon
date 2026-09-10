"""Single-open ingestion for the combined operational Unitka workbook."""

from dataclasses import dataclass
from io import BytesIO
from time import perf_counter
from typing import Callable

from openpyxl import load_workbook

from backend.domain.contracts import ImportResult, ProductEconomicsInput, ReportMeta, TariffRow
from .product_economics import import_product_economics
from .tariffs import import_tariffs
from .supplier_packaging import PackMultiplicityEvidence, import_supplier_packaging


@dataclass(frozen=True, slots=True)
class UnitkaImportBundle:
    product_economics: ImportResult[ProductEconomicsInput]
    tariffs: ImportResult[TariffRow]
    pack_multiplicity: ImportResult[PackMultiplicityEvidence]


def import_unitka_bundle(data: bytes, report_context: ReportMeta, *,
                         timing: Callable[[str, float, int | None], None] | None = None) -> UnitkaImportBundle:
    """Open Unitka once and preserve the standalone importers' parser contracts."""
    started = perf_counter()
    workbook = load_workbook(BytesIO(data), read_only=False, data_only=True)
    if timing:
        timing("unitka_open", perf_counter() - started, None)
    try:
        started = perf_counter()
        tariffs = import_tariffs(data, report_context, workbook=workbook)
        if timing:
            timing("unitka_tariffs", perf_counter() - started, len(tariffs.records))
        started = perf_counter()
        products = import_product_economics(data, report_context, workbook=workbook)
        if timing:
            timing("unitka_economics", perf_counter() - started, len(products.records))
        started = perf_counter()
        packs = import_supplier_packaging(data, report_context, workbook=workbook)
        if timing:
            timing("unitka_pack_multiplicity", perf_counter() - started, len(packs.records))
        return UnitkaImportBundle(products, tariffs, packs)
    finally:
        workbook.close()
