"""A reply's remote media is fetched only from a public address.

``_send_image`` / ``_send_file`` / ``_send_voice`` all hand the URL from the
Agent's reply to ``_download_remote_media``, and the bytes come back out in the
chat. The URL is therefore whatever a prompt — or a page it read — pointed at,
and ``download_to_file`` bounded the size and nothing else: a loopback address,
a link-local one, or the cloud metadata endpoint were all fetched.

``guard_public`` routes the request through the same redirect-aware guard the
tools use, so the address is checked before the first request and re-checked on
every hop. These drive the real ``_download_remote_media`` over a stubbed
transport, with name resolution stubbed rather than the guard itself.
"""

import socket

import pytest
import requests

import channel.wecom_bot.wecom_bot_channel as wecom
from common import media_download

PUBLIC_URL = "https://cdn.example.com/pic.png"
PUBLIC_IP = "93.184.216.34"

# A chain that starts public and 3xxs onto the host itself. The reply only ever
# named the first URL.
REDIRECT_TO_LOOPBACK = "https://cdn.example.com/hop"

IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" * 8


class FakeResponse:
    def __init__(self, status_code=200, chunks=(IMAGE_BYTES,), headers=None):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "image/png", "Content-Length": str(len(IMAGE_BYTES))}
        self._chunks = list(chunks)
        # safe_get reads these properties, not status_code, to decide whether
        # to follow a hop.
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
def media_path(tmp_path, monkeypatch):
    """Keep the download inside the test's directory."""
    monkeypatch.setattr(wecom, "_media_tmp_path", lambda prefix, ext="": str(tmp_path / f"{prefix}{ext}"))
    return tmp_path


def _transport(monkeypatch, responder):
    """Record every request the download makes, answering with *responder*."""
    seen = []

    def get(url, **kwargs):
        seen.append(dict(kwargs, url=url))
        return responder(url)

    # ``safe_get`` calls requests.get at call time, so one stub covers the guard
    # and the save that follows it.
    monkeypatch.setattr(requests, "get", get)
    return seen


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
def test_a_non_public_address_is_never_requested(url, media_path, monkeypatch):
    seen = _transport(monkeypatch, lambda _u: pytest.fail("a non-public address was requested"))

    with pytest.raises(ValueError, match="non-public"):
        wecom._download_remote_media(url, "wecom_img", None, 10 * 1024 * 1024, 30)

    assert seen == []
    assert list(media_path.iterdir()) == [], "a refused download leaves nothing behind"


def test_a_public_image_still_lands(resolves, media_path, monkeypatch):
    seen = _transport(monkeypatch, lambda _u: FakeResponse())

    path, size, content_type = wecom._download_remote_media(
        PUBLIC_URL, "wecom_img", None, 10 * 1024 * 1024, 30
    )

    assert size == len(IMAGE_BYTES)
    assert content_type == "image/png"
    # ext=None means the suffix comes from the served type.
    assert path.endswith(".png")
    with open(path, "rb") as handle:
        assert handle.read() == IMAGE_BYTES
    # Streamed, so the size cap counts chunks instead of buffering the body.
    assert seen[0]["stream"] is True
    # Auto-redirect off, so each hop can be checked before it is followed.
    assert seen[0]["allow_redirects"] is False


def test_a_redirect_onto_this_host_is_refused(resolves, media_path, monkeypatch):
    def responder(url):
        if url == REDIRECT_TO_LOOPBACK:
            return FakeResponse(
                status_code=302, headers={"Location": "http://127.0.0.1:8080/x.png"}
            )
        return FakeResponse()

    seen = _transport(monkeypatch, responder)

    with pytest.raises(ValueError, match="non-public"):
        wecom._download_remote_media(REDIRECT_TO_LOOPBACK, "wecom_file", ".bin", 10 * 1024 * 1024, 60)

    assert [call["url"] for call in seen] == [REDIRECT_TO_LOOPBACK]
    assert list(media_path.iterdir()) == []


def test_an_explicit_extension_is_kept(resolves, media_path, monkeypatch):
    _transport(monkeypatch, lambda _u: FakeResponse())

    path, _size, _ct = wecom._download_remote_media(
        PUBLIC_URL, "wecom_voice", ".mp3", 10 * 1024 * 1024, 60
    )

    assert path.endswith(".mp3")


def test_an_oversized_download_is_refused(resolves, media_path, monkeypatch):
    _transport(
        monkeypatch,
        lambda _u: FakeResponse(
            headers={"Content-Type": "image/png", "Content-Length": str(10 * 1024 * 1024 + 1)}
        ),
    )

    with pytest.raises(media_download.MediaTooLargeError):
        wecom._download_remote_media(PUBLIC_URL, "wecom_img", None, 10 * 1024 * 1024, 30)

    assert list(media_path.iterdir()) == []


def test_every_reply_media_path_goes_through_the_guarded_downloader():
    """Image, file and voice replies all have to reach the guard.

    The three senders each grew an ``http(s)`` branch of their own; a fourth
    one added later would otherwise be unguarded until someone noticed.
    """
    import inspect

    cls = getattr(wecom.WecomBotChannel, "__wrapped__", wecom.WecomBotChannel)
    callers = [
        name
        for name in ("_send_image", "_send_file", "_send_voice")
        if "_download_remote_media(" in inspect.getsource(getattr(cls, name))
    ]
    assert sorted(callers) == ["_send_file", "_send_image", "_send_voice"]

    # And the downloader itself asks for the unconditional guard, rather than
    # each caller remembering to.
    assert 'guard="always"' in inspect.getsource(wecom._download_remote_media)
