# encoding:utf-8
"""WebFetch._fetch_webpage refuses pages over MAX_FILE_SIZE instead of buffering them whole."""

import io

import requests

from agent.tools.web_fetch import web_fetch as web_fetch_module
from agent.tools.web_fetch.web_fetch import WebFetch

LIMIT = 4096
PAGE = b"<html><head><title>Report</title></head><body><p>Revenue is 42.</p></body></html>"


class _Raw(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.bytes_read = 0

    def read(self, size=-1):
        data = super().read(size)
        self.bytes_read += len(data)
        return data


def _fetch(monkeypatch, body, content_length=None):
    monkeypatch.setenv("WEB_SECURITY_SSRF_PROTECTION", "false")
    monkeypatch.setattr(web_fetch_module, "MAX_FILE_SIZE", LIMIT)
    resp = requests.Response()
    resp.status_code = 200
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    if content_length is not None:
        resp.headers["Content-Length"] = str(content_length)
    resp.raw = _Raw(body)
    monkeypatch.setattr(web_fetch_module, "safe_get", lambda url, **kw: resp)
    return WebFetch(config={"cwd": "."}).execute({"url": "https://example.com/page"}), resp.raw


def test_declared_oversize_page_is_refused_unread(monkeypatch):
    result, raw = _fetch(monkeypatch, PAGE, content_length=512 * 1024 * 1024)
    assert result.status == "error" and "too large" in result.result
    assert raw.bytes_read == 0


def test_headless_oversize_page_stops_reading(monkeypatch):
    body = b"<p>" + b"a" * (1024 * 1024) + b"</p>"
    result, raw = _fetch(monkeypatch, body)
    assert result.status == "error" and "too large" in result.result
    assert raw.bytes_read < len(body)


def test_small_page_is_extracted(monkeypatch):
    result, _ = _fetch(monkeypatch, PAGE, content_length=len(PAGE))
    assert result.status == "success", result.result
    assert "Revenue is 42." in result.result
