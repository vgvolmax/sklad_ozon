# XLSX regression payloads

Binary XLSX fixtures are intentionally not committed. Tests generate sanitized,
deterministic workbooks in memory with `tests/helpers/xlsx_fixtures.py`. The
malformed variant rewrites only the worksheet `<dimension>` declaration to
`ref="A1"` after openpyxl has created a normal workbook.
