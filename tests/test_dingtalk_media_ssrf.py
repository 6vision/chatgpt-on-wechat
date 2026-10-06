"""DingTalk reply media is fetched only from a public address.

``upload_media`` is the single entry every reply type goes through — image,
video, voice and file — and its ``http(s)`` branch called ``download_to_file``,
which bounds the size and nothing else. The URL is whatever the Agent's reply
carried, and the bytes are then uploaded to DingTalk, so a prompt (or a page it
read) could point the fetch at this host.

``guard="always"`` routes the request through the unconditional address check
and re-checks it on every redirect hop. These drive the real ``upload_media``
over a stubbed transport, with name resolution stubbed rather than the guard.
"""

import socket
from types import SimpleNamespace
from unittest import mock

import pytest
import requests

import channel.dingtalk.dingtalk_channel as dingtalk
from common.media_download import MAX_FILE_BYTES

PUBLIC_URL = "https://cdn.example.com/pic.png"
PUBLIC_IP = "93.184.216.34"

# Starts public, 3xxs onto this host. The reply only ever named the first URL.
REDIRECT_TO_LOOPBACK = "https://cdn.example.com/hop"

IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" * 8


class FakeResponse:
    def __init__(self, status_code=200, chunks=(IMAGE_BYTES,), headers=None):
        self.status_code = status_code
        self.headers = headers or {
            "Content-Type": "image/png",
            "Content-Length": str(len(IMAGE_BYTES)),
        }
        self._chunks = list(chunks)
        self.is_redirect = status_code in (301, 302, 303, 307, 308)
        self.is_permanent_redirect = status_code in (301, 308)
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        yield from self._chunks

    def close(self):
        self.closed = True


@pytest.fixture
def resolves(monkeypatch):
    """Resolve every hostname to one public address."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 0))
        ],
    )


@pytest.fixture
def channel(monkeypatch, tmp_path):
    """A bare channel whose uploads land in the test's directory."""
    cls = getattr(dingtalk.DingTalkChanel, "__wrapped__", dingtalk.DingTalkChanel)
    instance = cls.__new__(cls)
    instance.get_access_token = lambda: "token"
    monkeypatch.setattr(
        dingtalk.state_dir, "tmp_dir", lambda: tmp_path
    )
    return instance


def _transport(monkeypatch, responder):
    """Record every request the download makes, answering with *responder*."""
    seen = []

    def get(url, **kwargs):
        seen.append(dict(kwargs, url=url))
        return responder(url)

    monkeypatch.setattr(requests, "get", get)
    return seen


def _upload(channel, url, media_type="image"):
    """Run the real upload path with DingTalk's own POST stubbed out."""
    posted = []

    def post(url, **kwargs):
        posted.append(url)
        return SimpleNamespace(
            status_code=200,
            content=b"{}",
            json=lambda: {"errcode": 0, "media_id": "media_ok"},
        )

    with mock.patch.object(dingtalk.requests, "post", post):
        result = channel.upload_media(url, media_type)
    return result, posted


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/secret.png",
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://10.0.0.5/internal.png",
        "http://169.254.1.1/admin.png",
        "http://[::1]/image.png",
    ],
)
@pytest.mark.parametrize("media_type", ["image", "file"])
def test_a_non_public_address_is_never_requested(url, media_type, channel, tmp_path, monkeypatch):
    seen = _transport(monkeypatch, lambda _u: pytest.fail("a non-public address was requested"))

    result, posted = _upload(channel, url, media_type)

    assert result is None
    assert seen == []
    assert posted == [], "refused bytes must not reach DingTalk"
    assert list(tmp_path.iterdir()) == [], "a refused download leaves nothing behind"


def test_a_public_image_still_uploads(resolves, channel, tmp_path, monkeypatch):
    seen = _transport(monkeypatch, lambda _u: FakeResponse())

    result, posted = _upload(channel, PUBLIC_URL, "image")

    assert result == "media_ok"
    assert posted, "the upload leg must run"
    # The sanitized last path segment names the temp file.
    assert (tmp_path / "pic.png").read_bytes() == IMAGE_BYTES
    # Streamed, so the size cap counts chunks rather than buffering the body.
    assert seen[0]["stream"] is True
    # Auto-redirect off, so each hop's address can be checked before it is followed.
    assert seen[0]["allow_redirects"] is False


def test_a_redirect_onto_this_host_is_refused(resolves, channel, tmp_path, monkeypatch):
    def responder(url):
        if url == REDIRECT_TO_LOOPBACK:
            return FakeResponse(
                status_code=302, headers={"Location": "http://127.0.0.1:8080/x.png"}
            )
        return FakeResponse()

    seen = _transport(monkeypatch, responder)

    result, posted = _upload(channel, REDIRECT_TO_LOOPBACK, "image")

    assert result is None
    # The first hop was checked and followed; the second address never got a
    # request, because the guard resolves before it opens the connection.
    assert [call["url"] for call in seen] == [REDIRECT_TO_LOOPBACK]
    assert posted == []
    assert list(tmp_path.iterdir()) == []


def test_a_declared_oversize_is_refused_before_any_chunk(resolves, channel, tmp_path, monkeypatch):
    _transport(
        monkeypatch,
        lambda _u: FakeResponse(
            headers={
                "Content-Type": "image/png",
                "Content-Length": str(MAX_FILE_BYTES + 1),
            }
        ),
    )

    result, posted = _upload(channel, PUBLIC_URL, "image")

    assert result is None
    assert posted == []
    assert list(tmp_path.iterdir()) == []


def test_a_query_string_does_not_reach_the_file_name(resolves, channel, tmp_path, monkeypatch):
    """The name comes from the path only; a query may carry a token."""
    _transport(monkeypatch, lambda _u: FakeResponse())

    result, _posted = _upload(channel, "https://cdn.example.com/pic.png?token=s3cret", "image")

    assert result == "media_ok"
    assert [p.name for p in tmp_path.iterdir()] == ["pic.png"]


def test_the_shared_guard_is_asked_for_unconditionally():
    """A delivery path must not follow the tool-level opt-in."""
    import inspect

    cls = getattr(dingtalk.DingTalkChanel, "__wrapped__", dingtalk.DingTalkChanel)
    assert 'guard="always"' in inspect.getsource(cls.upload_media)
