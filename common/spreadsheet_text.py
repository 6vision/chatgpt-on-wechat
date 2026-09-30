"""Excel text extraction that preserves formulas lacking cached results."""

from contextlib import contextmanager


def _sheet_rows(cached_sheet, formula_sheet):
    for cached_row, formula_row in zip(cached_sheet.iter_rows(), formula_sheet.iter_rows()):
        values = []
        for cached, source in zip(cached_row, formula_row):
            value = cached.value
            if value is None and source.data_type == "f":
                value = f"[Formula: {source.value} (not calculated)]"
            values.append(str(value) if value is not None else "")
        yield values


@contextmanager
def spreadsheet_sheets(file_path, load_workbook):
    """Yield sheet names/rows and close both read-only views on every exit.

    Keep valid cached values (including zero/False). A missing cache falls back
    to the formula text, explicitly marked as unevaluated; no recalculation is
    attempted. The loader remains supplied by the optional-dependency callers.
    """
    cached = load_workbook(file_path, read_only=True, data_only=True)
    try:
        formulas = load_workbook(file_path, read_only=True, data_only=False)
        try:
            yield ((sheet.title, _sheet_rows(sheet, formulas[sheet.title])) for sheet in cached.worksheets)
        finally:
            formulas.close()
    finally:
        cached.close()
