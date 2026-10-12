"""Missing Excel caches must not erase formulas or replace valid caches."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET

import pytest
import requests

from agent.tools.read.read import Read
from agent.tools.web_fetch.web_fetch import WebFetch


@pytest.mark.parametrize("tool_name", ["read", "web_fetch"])
def test_uncached_formula_is_visible_while_cached_result_is_preserved(tmp_path, monkeypatch, tool_name):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = "=SUM(1,2)"
    sheet["B1"] = "=10+20"
    sheet["C1"] = 0
    workbook.create_sheet("FormulaOnly")["A1"] = "=MAX(4,5)"
    path = tmp_path / "calculations.xlsx"
    workbook.save(path)
    workbook.close()

    # Add an actual Excel cached result to B1; openpyxl itself writes no caches.
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    xml = ET.fromstring(members["xl/worksheets/sheet1.xml"])
    xml.find(".//s:c[@r='B1']/s:v", namespace).text = "30"
    members["xl/worksheets/sheet1.xml"] = ET.tostring(xml)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)

    if tool_name == "read":
        result = Read({"cwd": str(tmp_path)}).execute({"path": str(path)})
        text = result.result.get("content", "")
    else:
        tool = WebFetch({"cwd": str(tmp_path)})
        response = requests.Response()
        response.status_code = 200
        response.raw = BytesIO(path.read_bytes())
        response.headers["Content-Length"] = str(path.stat().st_size)
        monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
        # Intercept only HTTP; genuine XLSX bytes and both parsers remain real.
        monkeypatch.setattr(tool, "_safe_get", lambda *_args, **_kwargs: response)
        result = tool.execute({"url": "https://example.test/calculations.xlsx"})
        text = result.result

    assert result.status == "success", result.result
    assert "=SUM(1,2)" in text
    assert "not calculated" in text
    assert "30" in text
    assert "=10+20" not in text
    assert "=MAX(4,5)" in text
    assert "FormulaOnly" in text
    assert "30\t0" in text or "30 | 0" in text
