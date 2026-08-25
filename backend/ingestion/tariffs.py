"""Validated tariff workbook importer with signature-based sheet selection."""

from io import BytesIO
from openpyxl import load_workbook

from backend.domain.contracts import ImportResult, ReportMeta, TariffRow
from ._common import _diag, parse_decimal
from .normalization import normalize_header, normalize_text

_ALIASES = {
    "кластер отгрузки": "origin", "кластер отправления": "origin", "origin cluster": "origin",
    "кластер доставки": "destination", "destination cluster": "destination",
    "объём от": "min_volume", "объем от": "min_volume", "min volume": "min_volume",
    "объём до": "max_volume", "объем до": "max_volume", "max volume": "max_volume",
    "цена от": "min_price", "min price": "min_price", "цена до": "max_price", "max price": "max_price",
    "логистика": "fee", "тариф": "fee", "logistics fee": "fee",
}
_REQUIRED = frozenset({"origin", "destination", "min_volume", "fee"})


def import_tariffs(data: bytes, report_context: ReportMeta) -> ImportResult[TariffRow]:
    if not data.startswith(b"PK"):
        return ImportResult((), (_diag("TARIFF_SHEET_NOT_FOUND", "Tariffs require an XLSX workbook with a recognizable tariff sheet."),), report_context)
    workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    matches = []
    for worksheet in workbook.worksheets:
        for header_row, first in enumerate(worksheet.iter_rows(max_row=30, values_only=True), 1):
            names=tuple(normalize_header(value) for value in first)
            mapped = tuple(_ALIASES.get(name, "") for name in names)
            if _REQUIRED <= set(mapped): matches.append((worksheet.title, mapped, header_row, False)); break
            real={"кластер поставки","кластер доставки","для товаров до 300 руб.","для товаров свыше 300 руб."}
            if real <= set(names): matches.append((worksheet.title,names,header_row,True)); break
    if len(matches) != 1:
        workbook.close()
        code = "TARIFF_SHEET_NOT_FOUND" if not matches else "AMBIGUOUS_TARIFF_SHEETS"
        return ImportResult((), (_diag(code, "No tariff sheet matched required columns." if not matches else "Multiple sheets matched tariff columns."),), report_context)
    name, mapped, header_row, real = matches[0]; worksheet = workbook[name]
    records, sources, diagnostics = [], [], []
    for row_number, values in enumerate(worksheet.iter_rows(min_row=header_row+1, values_only=True), start=header_row+1):
        if real:
            raw=dict(zip(mapped,values,strict=False))
            origin=normalize_text(raw.get("кластер поставки")); destination=normalize_text(raw.get("кластер доставки"))
            volume=next((raw.get(k) for k in ("объём от","объем от","объём товара","объем товара") if k in raw),0)
            if not origin or not destination: continue
            try:
                min_volume=parse_decimal(volume); low=parse_decimal(raw.get("для товаров до 300 руб.")); high=parse_decimal(raw.get("для товаров свыше 300 руб."))
                if min_volume < 0 or low < 0 or high < 0: raise ValueError
            except ValueError:
                diagnostics.append(_diag("UNSUPPORTED_UNITKA_TARIFF_LAYOUT","FBO tariff row cannot be interpreted.",row=row_number)); continue
            records.extend((TariffRow(origin,destination,min_volume,None,None,Decimal("300"),low),
                            TariffRow(origin,destination,min_volume,None,Decimal("300"),None,high)))
            sources.extend((row_number,row_number)); continue
        row = dict(zip(mapped, values, strict=False))
        if not any(value is not None for value in values): continue
        origin, destination = normalize_text(row.get("origin")), normalize_text(row.get("destination"))
        if not origin or not destination:
            diagnostics.append(_diag("MALFORMED_ROW", "Origin and destination clusters must be nonblank.", row=row_number)); continue
        try:
            min_volume = parse_decimal(row.get("min_volume")); max_volume = parse_decimal(row.get("max_volume"), optional=True)
            min_price = parse_decimal(row.get("min_price"), optional=True); max_price = parse_decimal(row.get("max_price"), optional=True)
            fee = parse_decimal(row.get("fee"))
            if min_volume < 0 or fee < 0 or (min_price is not None and min_price < 0): raise ValueError
        except ValueError:
            diagnostics.append(_diag("INVALID_NUMBER", "Tariff numbers must be finite and non-negative.", row=row_number)); continue
        if max_volume is not None and max_volume < min_volume:
            diagnostics.append(_diag("INVALID_VOLUME_INTERVAL", "Maximum volume must not be below minimum volume.", row=row_number)); continue
        if max_price is not None and (max_price < 0 or min_price is not None and max_price < min_price):
            diagnostics.append(_diag("INVALID_PRICE_INTERVAL", "Maximum price must be non-negative and not below minimum price.", row=row_number)); continue
        records.append(TariffRow(origin, destination, min_volume, max_volume, min_price, max_price, fee)); sources.append(row_number)
    workbook.close()
    return ImportResult(tuple(records), tuple(diagnostics), report_context, tuple(sources))
