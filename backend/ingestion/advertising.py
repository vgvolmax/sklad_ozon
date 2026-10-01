"""Ozon product-promotion XLSX, explicitly grouped by day and SKU.

Percent columns are rounded vendor statistics, never the aggregation input.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import PurePath
import re
import zipfile

from backend.domain.advertising import AdvertisingDay, AdvertisingReport
from backend.ingestion.xlsx import iter_worksheet_rows

MAX_REPORT_DAYS = 366
MAX_REPORT_CELLS = 300_000


def _header(value):
    return re.sub(r'[^a-zа-я0-9]', '', str(value or '').casefold().replace('ё', 'е'))


def _sku(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('SKU отсутствует или заполнен неверно.')
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number != number.to_integral_value():
            raise ValueError('SKU должен быть целым положительным числом.')
        result = str(int(number))
        if len(result) > 80: raise ValueError('SKU слишком длинный.')
        return result
    value = str(value).strip()
    if not value or len(value) > 80 or any(c.isspace() for c in value):
        raise ValueError('SKU отсутствует или заполнен неверно.')
    if re.fullmatch(r'\d+\.0+', value):
        return str(int(Decimal(value)))
    return value


def _money(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Расход должен быть числом, включая явный ноль.')
    try:
        result = Decimal(str(value).strip().replace('\xa0', '').replace(' ', '').replace(',', '.'))
    except InvalidOperation:
        raise ValueError('Расход должен быть числом.') from None
    if not result.is_finite() or not 0 <= result <= Decimal('1000000000000'):
        raise ValueError('Расход должен быть конечным неотрицательным числом.')
    return result.quantize(Decimal('.01'))


def _day(value):
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    for pattern in ('%d.%m.%Y', '%Y-%m-%d'):
        try: return datetime.strptime(str(value).strip(), pattern).date()
        except ValueError: pass
    raise ValueError('День должен быть датой ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.')


def import_advertising(content: bytes, filename: str) -> AdvertisingReport:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if len(archive.infolist()) > 2000 or sum(i.file_size for i in archive.infolist()) > 128 * 1024 * 1024:
                raise ValueError('Распакованный XLSX слишком большой.')
        source = iter_worksheet_rows(BytesIO(content), 0, max_cells=MAX_REPORT_CELLS)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Не удалось прочитать XLSX. Загрузите отчёт Ozon по товарам с группировкой по дням.') from exc
    preamble = ' '.join(str(v) for row in source.rows[:20] for v in row.values[:1])
    period = re.search(r'Период\s*:\s*(\d{2}\.\d{2}\.\d{4})\s*[-–—]\s*(\d{2}\.\d{2}\.\d{4})', preamble, re.I)
    campaign = re.search(r'Кампания[^\n]*?№\s*(\d+)', preamble, re.I)
    if period is None or campaign is None:
        raise ValueError('В XLSX не найдены период и номер кампании Ozon.')
    start, end = (_day(v) for v in period.groups())
    if not 0 <= (end - start).days < MAX_REPORT_DAYS:
        raise ValueError('Период отчёта должен содержать от 1 до 366 дней.')
    if len(campaign.group(1)) > 32:
        raise ValueError('Номер кампании слишком длинный.')
    campaign_id = str(int(campaign.group(1)))
    if campaign_id == '0': raise ValueError('Номер кампании заполнен неверно.')
    header = None
    for index, row in enumerate(source.rows[:20]):
        names = [_header(v) for v in row.values]
        if 'sku' in names and 'день' in names:
            candidates = [i for i, name in enumerate(names) if name in {'расходсндс', 'расход', 'расходндс'}]
            if len(candidates) != 1 or names.count('sku') != 1 or names.count('день') != 1:
                raise ValueError('Нужны однозначные колонки «День», «SKU» и «Расход, ₽, с НДС».')
            header = index, names.index('день'), names.index('sku'), candidates[0]
            break
    if header is None:
        raise ValueError('Выберите отчёт по товарам с группировкой по дням: нужны «День», «SKU» и «Расход».')
    index, day_column, sku_column, spend_column = header
    entries = {}
    total = None
    for row in source.rows[index + 1:]:
        values = row.values
        if _header(values[0]) in {'всего', 'итого'}:
            if total is not None: raise ValueError('В отчёте несколько итогов расходов.')
            total = _money(values[spend_column] if len(values) > spend_column else None)
            continue
        try:
            day = _day(values[day_column])
            sku = _sku(values[sku_column])
            spend = _money(values[spend_column])
        except (ValueError, IndexError) as exc:
            raise ValueError(f'Строка {row.source_row}: {exc}') from None
        if not start <= day <= end:
            raise ValueError(f'Строка {row.source_row}: дата вне периода отчёта.')
        if (sku, day) in entries:
            raise ValueError(f'Строка {row.source_row}: повтор SKU и дня. Выберите группировку только по дням.')
        entries[sku, day] = spend
    if not entries: raise ValueError('В отчёте нет товарных строк.')
    if total is None:
        raise ValueError('В отчёте нет строки «Всего» с расходом. Загрузите полный отчёт кампании.')
    warning = None
    if total is not None:
        difference = abs(sum(entries.values(), Decimal('0')) - total)
        # Ozon rounds product/day cells independently of its total. The
        # maximum possible cent-rounding drift is half a cent per cell.
        tolerance = Decimal('.005') * (len(entries) + 1)
        if difference > max(Decimal('.01'), tolerance):
            raise ValueError('Итог расходов не совпадает с товарными строками. Загрузите полный отчёт кампании.')
        if difference > Decimal('.01'):
            warning = f'Итог отличается от суммы строк на {difference:.2f} ₽ в пределах округления. Использована сумма дневных строк.'
    # A complete daily export is explicit period evidence. Missing activity
    # days inside that report have zero cost; absent SKU are never zero-filled.
    skus = sorted({sku for sku, _ in entries})
    if len(skus) * ((end - start).days + 1) > 100_000:
        raise ValueError('Слишком много товарных дней. Разделите отчёт.')
    days = tuple(AdvertisingDay(campaign_id, sku, start + timedelta(days=offset),
                               entries.get((sku, start + timedelta(days=offset)), Decimal('0')))
                 for sku in skus
                 for offset in range((end - start).days + 1))
    return AdvertisingReport(campaign_id, start, end, PurePath(filename).name[:200], days, warning)
