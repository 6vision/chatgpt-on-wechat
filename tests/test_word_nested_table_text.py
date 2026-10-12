"""Word table cells keep nested paragraphs and tables in reading order."""

import pytest

from common.office_text import iter_docx_body_text


def test_nested_cell_content_keeps_its_order():
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Report beginning")
    table = document.add_table(rows=1, cols=2)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = "Before nested table"
    inner = cell.add_table(rows=1, cols=2)
    inner.cell(0, 0).text = "Region"
    inner.cell(0, 1).add_table(rows=1, cols=1).cell(0, 0).text = "Approved allocation"
    cell.add_paragraph("After nested table")
    table.cell(0, 1).text = "Right-hand cell"
    document.add_paragraph("Report ending")

    text = "\n".join(iter_docx_body_text(document))
    expected = ["Report beginning", "Before nested table", "Region", "Approved allocation",
                "After nested table", "Right-hand cell", "Report ending"]
    positions = [text.index(piece) for piece in expected]
    assert positions == sorted(positions)
    assert text.count("Approved allocation") == 1
