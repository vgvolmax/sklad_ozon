"""Importer for seller-owned product economics input state."""

from decimal import Decimal
from backend.domain.contracts import ImportResult, ProductEconomicsInput, ReportMeta
from ._common import _diag, parse_decimal, read_source_rows, read_xlsx_tables
from .normalization import normalize_text

_HEADERS = {"sku": "sku", "артикул": "article", "себестоимость": "cost", "доступный остаток": "available", "цена": "price", "комиссия": "commission", "объём, л": "volume", "объем, л": "volume"}
_HEADERS.update({"себестоимость единицы":"cost", "цена поставщика до скидок ozon":"price",
                 "комиссия ozon %":"commission", "объём товара":"volume", "объем товара":"volume",
                 "объём товара (л)":"volume", "объем товара (л)":"volume"})
_REQUIRED = frozenset({"sku", "article", "cost", "available", "price", "commission", "volume"})


def _rate(value: object) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()): return None
    text = str(value).strip()
    percent = text.endswith("%")
    rate = parse_decimal(text[:-1] if percent else text)
    if percent: rate /= 100
    if rate < 0 or rate > 1: raise ValueError
    return rate


def import_product_economics(data: bytes, report_context: ReportMeta, *, workbook=None) -> ImportResult[ProductEconomicsInput]:
    source = (read_xlsx_tables(data, lambda h: _REQUIRED <= {_HEADERS[x] for x in h if x in _HEADERS} or {"артикул","себестоимость единицы","цена поставщика до скидок ozon","комиссия ozon %"} <= set(h), workbook=workbook)
              if data.startswith(b"PK") else read_source_rows(data)); diagnostics = list(source.diagnostics)
    keys = {_HEADERS[key] for key in source.rows[0][1] if key in _HEADERS} if source.rows else set()
    real = "article" in keys and "cost" in keys and "price" in keys and "commission" in keys and "volume" in keys
    missing = set() if real else _REQUIRED - keys
    if missing:
        diagnostics.append(_diag("MISSING_REQUIRED_HEADER", "Missing product economics columns.")); return ImportResult((), tuple(diagnostics), report_context)
    records, sources = [], []
    for row_number, raw in source.rows:
        row = {_HEADERS[key]: value for key, value in raw.items() if key in _HEADERS}
        sku = normalize_text(row.get("sku"))
        article = normalize_text(row.get("article"))
        if not sku and not article:
            continue
        try:
            cost = parse_decimal(row.get("cost"), optional=True); price = parse_decimal(row.get("price"), optional=True)
            volume = parse_decimal(row.get("volume"), optional=True)
            if any(value is not None and value < 0 for value in (cost, price, volume)): raise ValueError
        except ValueError:
            diagnostics.append(_diag("INVALID_NUMBER", "Economics values must be finite and non-negative.", row=row_number)); continue
        try:
            available_decimal = parse_decimal(row.get("available"), optional=True)
            if available_decimal is not None and (available_decimal < 0 or available_decimal != available_decimal.to_integral_value()): raise ValueError
            available = None if available_decimal is None else int(available_decimal)
        except ValueError:
            diagnostics.append(_diag("INVALID_QUANTITY", "Available seller stock must be a non-negative integer.", row=row_number)); continue
        try: commission = _rate(row.get("commission"))
        except ValueError:
            diagnostics.append(_diag("INVALID_RATE", "Commission must be a rate from zero to one; use % for whole percentages.", row=row_number)); continue
        records.append(ProductEconomicsInput(sku, article, cost, available, price, commission, volume)); sources.append(row_number)
    return ImportResult(tuple(records), tuple(diagnostics), report_context, tuple(sources))
