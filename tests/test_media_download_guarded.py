"""``guarded`` downloads honor web_security_ssrf_protection, redirects included."""

import pytest
import requests

from agent.tools.utils import url_safety
from common import media_download


class _Response:
    def __init__(self, status_code=200, location=None):
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}
        self.is_redirect = location is not None
        self.is_permanent_redirect = False
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield b"media"

    def close(self):
        self.closed = True


@pytest.fixture
def fetched(monkeypatch):
    urls = []
    replies = {"http://93.184.216.34/hop": _Response(302, "http://169.254.169.254/latest")}

    def get(url, **kwargs):
        urls.append(url)
        return replies.get(url, _Response())

    monkeypatch.setattr(requests, "get", get)
    return urls


def _protect(monkeypatch, enabled):
    monkeypatch.setattr(url_safety, "_ssrf_protection_enabled", lambda: enabled)


def test_private_url_is_refused_before_any_request(monkeypatch, fetched):
    _protect(monkeypatch, True)
    with pytest.raises(ValueError):
        media_download.download_bytes("http://127.0.0.1/secret", guarded=True)
    assert fetched == []


def test_redirect_into_a_private_address_is_refused(monkeypatch, fetched):
    _protect(monkeypatch, True)
    with pytest.raises(ValueError):
        media_download.download_bytes("http://93.184.216.34/hop", guarded=True)
    assert fetched == ["http://93.184.216.34/hop"]


def test_public_url_downloads(monkeypatch, fetched):
    _protect(monkeypatch, True)
    assert media_download.download_bytes("http://93.184.216.34/ok", guarded=True) == b"media"


@pytest.mark.parametrize("enabled, guarded", [(False, True), (True, False)])
def test_unchecked_when_off_or_unguarded(monkeypatch, fetched, enabled, guarded):
    _protect(monkeypatch, enabled)
    assert media_download.download_bytes("http://127.0.0.1/lan", guarded=guarded) == b"media"
