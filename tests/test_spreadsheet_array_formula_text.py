"""An uncalculated array formula shows its source, not an object repr."""

import pytest

from common.office_text import spreadsheet_sheets


def test_array_formula_without_cache_shows_its_source(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from openpyxl.worksheet.formula import ArrayFormula

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = ArrayFormula("A1:A3", "=SUM(B1:B3*C1:C3)")
    sheet["B1"] = "=SUM(1,2)"
    path = tmp_path / "array.xlsx"
    workbook.save(path)

    with spreadsheet_sheets(str(path), openpyxl.load_workbook) as sheets:
        rows = [row for _, sheet_rows in sheets for row in sheet_rows]

    assert rows[0][0] == "[Formula: =SUM(B1:B3*C1:C3) (not calculated)]"
    assert rows[0][1] == "[Formula: =SUM(1,2) (not calculated)]"
