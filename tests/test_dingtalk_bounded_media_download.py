# encoding: utf-8
"""DingTalk upload_media() must cap remote downloads (cf. #3300, Feishu).

It used a bare requests.get + f.write, so an oversized URL filled memory/disk.
Pin it to the shared download_to_file helper.
"""
import socket

import pytest

from tests.test_dingtalk_streaming_cards import _bare_channel


@pytest.fixture(autouse=True)
def _public_host(monkeypatch):
    """Resolve the reply URLs these tests use to a public address.

    Remote media is fetched only after its address has been checked, and the
    check resolves the hostname — a name that cannot resolve is refused before
    the request. These tests are about the size bound, so they need a host that
    resolves.
    """
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )


class FakeResp:
    def __init__(self, content=b"", headers=None, json_data=None, status=200):
        self.content = content
        self.headers = headers or {}
        self._json = json_data or {}
        self.status_code = status
        self.closed = False
        # safe_get reads these to decide whether a response is a hop to follow.
        self.is_redirect = status in (301, 302, 303, 307, 308)
        self.is_permanent_redirect = status in (301, 308)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %s" % self.status_code)

    def json(self):
        return self._json

    def iter_content(self, chunk_size):
        data = self.content
        step = chunk_size or 1
        for i in range(0, len(data), step):
            yield data[i:i + step]

    def close(self):
        self.closed = True


class _FakeReq:
    def __init__(self, get, post):
        self._get = get
        self._post = post

    def get(self, *a, **k):
        return self._get(*a, **k)

    def post(self, *a, **k):
        return self._post(*a, **k)


def _channel():
    ch = _bare_channel()
    ch.get_access_token = lambda: "tok"
    return ch


def _stub(monkeypatch, get_resp, post_resp, tmp_path):
    from agent.tools.utils import url_safety
    from channel.dingtalk import dingtalk_channel as mod

    fake = _FakeReq(lambda *a, **k: get_resp, lambda *a, **k: post_resp)
    monkeypatch.setattr(mod, "requests", fake)
    # The download goes through url_safety.safe_get, which calls requests.get
    # from its own module.
    monkeypatch.setattr(url_safety, "requests", fake)
    monkeypatch.setattr(
        "channel.dingtalk.dingtalk_channel.state_dir.tmp_dir",
        lambda *a, **k: str(tmp_path),
    )


def test_http_url_within_limit_returns_media_id(monkeypatch, tmp_path):
    get = FakeResp(content=b"<media data>", headers={"Content-Length": "20"})
    post = FakeResp(json_data={"errcode": 0, "media_id": "mid-1"})
    _stub(monkeypatch, get, post, tmp_path)
    assert _channel().upload_media("https://cdn.example/ok.mp4", "video") == "mid-1"


def test_http_url_over_size_limit_rejected(monkeypatch, tmp_path):
    from common.media_download import MAX_FILE_BYTES

    get = FakeResp(headers={"Content-Length": str(MAX_FILE_BYTES + 1)})
    post = FakeResp(json_data={"errcode": 0, "media_id": "mid-1"})
    _stub(monkeypatch, get, post, tmp_path)
    assert _channel().upload_media("https://evil.example/huge.bin", "file") is None


def test_http_url_query_string_stays_out_of_the_file_name(monkeypatch, tmp_path):
    get = FakeResp(content=b"<media data>")
    post = FakeResp(json_data={"errcode": 0, "media_id": "mid-3"})
    _stub(monkeypatch, get, post, tmp_path)
    url = "https://cdn.example/dir/%E6%8A%A5%E5%91%8A.pdf?token=secret&x=a/b"
    assert _channel().upload_media(url, "file") == "mid-3"
    assert [p.name for p in tmp_path.iterdir()] == ["报告.pdf"]


def test_local_file_url_still_uploaded(monkeypatch, tmp_path):
    local = tmp_path / "clip.mp4"
    local.write_bytes(b"<media data>")
    post = FakeResp(json_data={"errcode": 0, "media_id": "mid-2"})
    _stub(monkeypatch, FakeResp(), post, tmp_path)
    assert _channel().upload_media("file://" + str(local), "video") == "mid-2"
