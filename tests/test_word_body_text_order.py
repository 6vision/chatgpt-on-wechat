"""Both document tools preserve Word paragraphs and tables in body order."""

from io import BytesIO

import pytest
import requests

from agent.tools.read.read import Read
from agent.tools.web_fetch.web_fetch import WebFetch


@pytest.mark.parametrize("tool_name", ["read", "web_fetch"])
def test_word_tables_remain_between_their_surrounding_paragraphs(tmp_path, monkeypatch, tool_name):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("North budget")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "11 million"
    document.add_paragraph("South budget")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "22 million"
    document.add_paragraph("Report end")
    path = tmp_path / "report.docx"
    document.save(path)

    if tool_name == "read":
        result = Read({"cwd": str(tmp_path)}).execute({"path": str(path)})
        text = result.result.get("content", "")
    else:
        tool = WebFetch({"cwd": str(tmp_path)})
        response = requests.Response()
        response.status_code = 200
        response.raw = BytesIO(path.read_bytes())
        response.headers["Content-Length"] = str(path.stat().st_size)
        # Only the network boundary is intercepted; the public handler,
        # streamed download, local file and real python-docx parser execute.
        monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
        monkeypatch.setattr(tool, "_safe_get", lambda *_args, **_kwargs: response)
        result = tool.execute({"url": "https://example.test/report.docx"})
        text = result.result

    assert result.status == "success", result.result
    pieces = ["North budget", "11 million", "South budget", "22 million", "Report end"]
    positions = [text.index(piece) for piece in pieces]
    assert positions == sorted(positions)
