"""Compact backend-built Excel exports with numeric finance cells."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def _workbook(title, headers, rows, widths, *, percentages=(), freeze='A2'):
    book = Workbook()
    sheet = book.active
    sheet.title = title
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(name='Calibri', bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='087F73')
        cell.alignment = Alignment(wrap_text=True, vertical='center')
    sheet.row_dimensions[1].height = 32
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        sheet.row_dimensions[row[0].row].height = 42
        for index, cell in enumerate(row, 1):
            cell.font = Font(name='Calibri', size=11)
            cell.alignment = Alignment(wrap_text=True, vertical='center')
            if isinstance(cell.value, str):
                cell.data_type = 's'  # Article/name cannot become an Excel formula.
            if index in percentages:
                cell.number_format = '0.0%'
            elif isinstance(cell.value, (int, float)):
                cell.number_format = '#,##0.00'
            if cell.row % 2 == 0:
                cell.fill = PatternFill('solid', fgColor='E9EEF2')
    sheet.freeze_panes = freeze
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_title_rows = '1:1'
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def _number(value):
    return None if value is None else float(value)


def export_cost_prices(items):
    sources = {'manual': 'Ручная', 'import': 'Из юнитки'}
    rows = [[item['article'], item['product_name'], _number(item['cost']),
             sources[item['source']], item['updated_at']] for item in items]
    return _workbook('Себестоимость', ['Артикул', 'Товар', 'Себестоимость, ₽',
                                      'Источник', 'Обновлено (UTC)'], rows, [18, 60, 22, 18, 32])


def export_economics(report):
    skus = set()
    rows = []
    for product in sorted(report['products'], key=lambda p: (p['article'], p['sku'])):
        article = product['article']
        sku = product['sku']
        if not sku or sku in skus:
            raise ValueError('Нужен уникальный SKU для каждой строки отчёта.')
        skus.add(sku)
        rows.append([article, product['name'], _number(product['price']),
                     _number(product['planned_drr_rate']), _number(product['real_drr_rate']), _number(product['margin']),
                     _number(product['roi']), _number(report['target_margin']),
                     _number(product['target_price_all_routes']),
                     _number(product.get('applied_drr_rate')),
                     _number(product.get('commission_per_unit')),
                     (report.get('period') or {}).get('from'),
                     (report.get('period') or {}).get('to'), product['qty'], sku])
    return _workbook('Экономика', ['Артикул', 'Товар', 'Текущая цена, ₽',
        'ДРР по плану, %', 'Реальный ДРР, %', 'Маржа, %', 'ROI, %', 'Плановая маржа, %',
        'Необходимая цена, ₽', 'ДРР в расчёте, %', 'Комиссия Ozon, ₽ / шт.',
        'Период с', 'Период по', 'Доставлено, шт.', 'SKU'],
        rows, [18, 58, 22, 20, 20, 16, 16, 22, 24, 20, 24, 18, 18, 20, 24],
        percentages=(4, 5, 6, 7, 8, 10), freeze='C2')
