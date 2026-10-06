"""Local attachment names must not be interpreted as URL query/fragment syntax."""

import json
from pathlib import Path

import pytest

from channel.feishu.feishu_message import FeishuMessage
from common.utils import get_path_suffix
from agent.tools.read.read import Read


@pytest.mark.parametrize("filename", ["report#1.docx", "budget?Q4.docx", "report.docx"])
def test_feishu_document_name_preserves_parser_suffix(tmp_path, monkeypatch, filename):
    docx = pytest.importorskip("docx")
    monkeypatch.setattr("common.state_dir.tmp_dir", lambda: tmp_path)
    message = FeishuMessage({
        "app_id": "app", "sender": {"sender_id": {"open_id": "sender"}},
        "message": {
            "message_id": "message", "create_time": "1", "message_type": "file", "chat_id": "chat",
            "content": json.dumps({"file_key": "file_key", "file_name": filename}),
        },
    })
    document = docx.Document()
    document.add_paragraph("Quarterly revenue is 42 million.")
    document.save(message.content)
    result = Read({"cwd": str(tmp_path)}).execute({"path": message.content})
    assert Path(message.content).suffix == ".docx"
    assert result.status == "success", result.result
    assert "Quarterly revenue is 42 million." in result.result.get("content", "")


@pytest.mark.parametrize("path", ["/tmp/report#1.png", "/tmp/budget?Q4.png", "C:\\reports\\report#1.png"])
def test_local_image_suffix_is_not_a_url_fragment(path):
    assert get_path_suffix(path) == "png"


@pytest.mark.parametrize("url", ["https://example.test/image.png?size=2#preview", "http://example.test/image.png?size=2#preview"])
def test_remote_image_url_keeps_query_and_fragment_behavior(url):
    assert get_path_suffix(url) == "png"
