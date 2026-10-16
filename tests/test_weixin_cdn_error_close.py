"""The CDN connection is returned even when status validation rejects it."""

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

from channel.weixin import weixin_api
from common.media_download import MediaTooLargeError


class TrackedBody(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.releases = 0

    def release_conn(self):
        self.releases += 1


def _response(status, body):
    response = requests.Response()
    response.status_code = status
    response.url = "https://fixture.invalid/download"
    response.raw = TrackedBody(body)
    return response


@pytest.mark.parametrize("status", [404, 500])
def test_rejected_http_status_releases_the_stream_before_returning_error(tmp_path, monkeypatch, status):
    response = _response(status, b"error body that was not read")
    body = response.raw
    monkeypatch.setattr(weixin_api, "_get_cdn_session", lambda: SimpleNamespace(get=lambda *a, **k: response))
    destination = tmp_path / "attachment.bin"
    with pytest.raises(requests.HTTPError) as failed:
        weixin_api.download_media_from_cdn("https://fixture.invalid", "param", "00" * 16, str(destination))
    assert failed.value.response is response
    assert body.closed
    assert body.releases == 1
    assert not destination.exists()


def test_successful_download_still_decrypts_and_releases_the_connection(tmp_path, monkeypatch):
    key = bytes(range(16))
    plaintext = b"native attachment contents"
    response = _response(200, weixin_api._aes_ecb_encrypt(plaintext, key))
    body = response.raw
    monkeypatch.setattr(weixin_api, "_get_cdn_session", lambda: SimpleNamespace(get=lambda *a, **k: response))
    destination = tmp_path / "attachment.bin"
    assert weixin_api.download_media_from_cdn("https://fixture.invalid", "param", key.hex(), str(destination)) == str(destination)
    assert destination.read_bytes() == plaintext
    assert body.releases == 1


def test_oversized_body_remains_bounded_and_releases_the_connection(tmp_path, monkeypatch):
    response = _response(200, b"larger than the allowed fixture")
    body = response.raw
    monkeypatch.setattr(weixin_api, "_get_cdn_session", lambda: SimpleNamespace(get=lambda *a, **k: response))
    monkeypatch.setattr(weixin_api, "MAX_FILE_BYTES", 2)
    destination = tmp_path / "attachment.bin"
    with pytest.raises(MediaTooLargeError):
        weixin_api.download_media_from_cdn("https://fixture.invalid", "param", "00" * 16, str(destination))
    assert body.releases == 1
    assert not destination.exists()


def test_cleanup_failure_preserves_the_original_http_error(tmp_path, monkeypatch):
    response = _response(500, b"unread error")

    def failed_close():
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(response, "close", failed_close)
    monkeypatch.setattr(weixin_api, "_get_cdn_session", lambda: SimpleNamespace(get=lambda *a, **k: response))
    try:
        with pytest.raises(requests.HTTPError) as failed:
            weixin_api.download_media_from_cdn("https://fixture.invalid", "param", "00" * 16, str(tmp_path / "unused"))
        assert failed.value.response is response
    finally:
        response.raw.close()


def test_local_http_error_closes_the_native_stream_and_returns_the_pool_slot(tmp_path, monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_GET(self):
            body = b"native unread CDN error response"
            self.send_response(500)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = requests.Session()
    session.trust_env = False
    adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1, pool_block=True)
    session.mount("http://", adapter)
    monkeypatch.setattr(weixin_api, "_get_cdn_session", lambda: session)
    url = f"http://127.0.0.1:{server.server_port}"
    response = None
    try:
        with pytest.raises(requests.HTTPError) as failed:
            weixin_api.download_media_from_cdn(url, "param", "00" * 16, str(tmp_path / "unused"))
        response = failed.value.response
        assert response.raw.closed
        pool = response.raw._pool
        assert pool.num_connections == 1
        assert pool.pool.qsize() == 1, "the failed download retained the only streaming pool slot"
        assert not (tmp_path / "unused").exists()
    finally:
        if response is not None:
            response.close()
        session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
