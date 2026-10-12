# encoding:utf-8
"""Show-in-folder: only for a browser on this machine, only for allowed files."""

import json

import pytest
import web

from channel.web.api import files
from channel.web.core import _common


@pytest.fixture
def request_from(monkeypatch):
    def set_request(addr, body=None, **headers):
        env = {"REMOTE_ADDR": addr, **{f"HTTP_{k.upper()}": v for k, v in headers.items()}}
        monkeypatch.setattr(web, "ctx", web.storage(env=env, headers=[]), raising=False)
        monkeypatch.setattr(web, "header", lambda *a, **k: None)
        monkeypatch.setattr(web, "data", lambda: json.dumps(body or {}).encode())
    monkeypatch.setattr(files, "_require_auth", lambda: None)
    return set_request


def test_only_a_direct_local_request_may_reveal(request_from, monkeypatch):
    monkeypatch.setattr(_common.sys, "platform", "darwin")
    request_from("127.0.0.1")
    assert _common._can_reveal_in_file_manager() is True
    request_from("192.168.1.20")
    assert _common._can_reveal_in_file_manager() is False
    request_from("127.0.0.1", x_forwarded_for="203.0.113.9")
    assert _common._can_reveal_in_file_manager() is False


def test_a_headless_linux_box_offers_no_reveal(request_from, monkeypatch):
    monkeypatch.setattr(_common.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    request_from("127.0.0.1")
    assert _common._can_reveal_in_file_manager() is False


def test_reveal_opens_allowed_files_and_refuses_the_rest(request_from, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(files, "_can_reveal_in_file_manager", lambda: True)
    monkeypatch.setattr(files, "_reveal_path", opened.append)
    monkeypatch.setattr(files, "_is_path_allowed", lambda p: p.startswith(str(tmp_path.resolve())))
    doc = tmp_path / "guide.docx"
    doc.write_bytes(b"x")

    request_from("127.0.0.1", {"path": str(doc)})
    assert json.loads(files.FileRevealHandler().POST())["status"] == "success"
    assert opened == [str(doc.resolve())]

    for path in ("/etc/hosts", "relative/guide.docx", str(tmp_path / "missing.docx")):
        request_from("127.0.0.1", {"path": path})
        assert json.loads(files.FileRevealHandler().POST())["status"] == "error"
    assert len(opened) == 1


def test_reveal_is_refused_when_not_local(request_from, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(files, "_can_reveal_in_file_manager", lambda: False)
    monkeypatch.setattr(files, "_reveal_path", opened.append)
    request_from("10.0.0.5", {"path": str(tmp_path)})
    assert json.loads(files.FileRevealHandler().POST())["status"] == "error"
    assert opened == []
