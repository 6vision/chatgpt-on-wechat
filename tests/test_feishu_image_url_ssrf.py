"""A remote image the Agent names must be fetched through the public-image guard.

The Markdown-image path already is. ``ReplyType.IMAGE_URL`` was not: it went
straight to ``download_bytes``, which bounds the size but not the destination,
and the bytes it fetched were uploaded to Feishu and handed back as an
``image_key`` — so anything the Agent could be steered into naming was fetched
and put in the chat.

These drive the real ``_upload_image_url``. Name resolution is stubbed, not the
transport, so the guard under test is the production one; the public address it
resolves to is what any real hostname would have to answer with.
"""

import socket
from types import SimpleNamespace

import pytest

from channel.feishu import feishu_channel, feishu_static_card
from channel.feishu.feishu_channel import FeiShuChanel

PUBLIC_URL = "https://cdn.example.com/chart.png"
PUBLIC_IP = "93.184.216.34"

# A chain that starts on a public host and 3xxs to a loopback address. The model
# only ever named the first URL.
REDIRECT_TO_LOOPBACK = "https://cdn.example.com/redirect"


class FakeResponse:
    def __init__(self, status_code=200, chunks=(b"png-bytes",), headers=None):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "image/png"}
        self._chunks = list(chunks)
        self.closed = False

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size):
        yield from self._chunks


def _ok_upload(image_key="img_v2_chart"):
    def post(url, files=None, data=None, headers=None, timeout=None):
        post.calls.append({"url": url, "files": files, "timeout": timeout})
        return SimpleNamespace(
            content=b"{}", json=lambda: {"code": 0, "data": {"image_key": image_key}}
        )

    post.calls = []
    return post


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
def uploaded(monkeypatch):
    """Record the multipart upload and report a successful image_key."""
    post = _ok_upload()
    monkeypatch.setattr("channel.feishu.feishu_channel.requests.post", post)
    return post


def _channel():
    # _upload_image_url touches no instance state and the class is wrapped by
    # @singleton, so build a bare instance from the undecorated class.
    cls = FeiShuChanel.__wrapped__
    return cls.__new__(cls)


def _transport(monkeypatch, responder):
    """Route the guard's requests through *responder*, recording the URLs.

    Two bindings stand between the test and the wire. ``feishu_channel``
    imported ``download_public_image`` by name, so the name to replace is the
    one in *that* module; and that function takes ``get=requests.get`` as a
    default argument, bound when its own module loaded, so patching the
    attribute on ``requests`` would not reach it either. The real guard runs —
    only its transport is swapped.
    """
    seen = []

    def get(url, **kwargs):
        seen.append(dict(kwargs, url=url))
        return responder(url)

    real = feishu_static_card.download_public_image

    def wrapper(url, max_bytes=feishu_static_card._MAX_REMOTE_IMAGE_BYTES):
        return real(url, max_bytes=max_bytes, get=get)

    monkeypatch.setattr(feishu_channel, "download_public_image", wrapper)
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
def test_a_non_public_address_is_never_requested(url, uploaded, monkeypatch):
    """The guard runs before the request, not after it."""
    seen = _transport(
        monkeypatch, lambda _u: pytest.fail("a non-public address was requested")
    )

    assert _channel()._upload_image_url(url, "token") is None
    assert seen == []
    assert uploaded.calls == [], "refused bytes must not reach the upload"


def test_a_public_image_still_uploads(resolves, uploaded, monkeypatch):
    """The normal path is unchanged: fetch, name it by its served type, upload."""
    seen = _transport(monkeypatch, lambda _u: FakeResponse())

    assert _channel()._upload_image_url(PUBLIC_URL, "token") == "img_v2_chart"

    assert [call["url"] for call in seen] == [PUBLIC_URL]
    # The guard disables auto-redirect so it can validate every hop itself.
    assert seen[0]["allow_redirects"] is False
    name, payload = uploaded.calls[0]["files"]["image"]
    assert payload == b"png-bytes"
    # The filename follows what the server sent, not the URL's extension.
    assert name == "image.png"


def test_a_redirect_into_a_private_address_is_refused(resolves, uploaded, monkeypatch):
    """A public URL that 3xxs inward is exactly what a pre-flight check misses."""
    def responder(url):
        if url == REDIRECT_TO_LOOPBACK:
            return FakeResponse(
                status_code=302, headers={"Location": "http://127.0.0.1:8080/x.png"}
            )
        return FakeResponse()

    seen = _transport(monkeypatch, responder)

    assert _channel()._upload_image_url(REDIRECT_TO_LOOPBACK, "token") is None
    # The first hop was checked and followed; the second address never got a
    # request, because the guard resolves before it opens the connection.
    assert [call["url"] for call in seen] == [REDIRECT_TO_LOOPBACK]
    assert uploaded.calls == []


def test_a_non_image_content_type_is_refused(resolves, uploaded, monkeypatch):
    """The reply named an image; the server sent HTML. It is not uploaded."""
    _transport(
        monkeypatch,
        lambda _u: FakeResponse(headers={"Content-Type": "text/html"}, chunks=[b"<html>"]),
    )

    assert _channel()._upload_image_url(PUBLIC_URL, "token") is None
    assert uploaded.calls == []


def test_an_oversized_image_is_refused(resolves, uploaded, monkeypatch):
    _transport(
        monkeypatch,
        lambda _u: FakeResponse(
            headers={
                "Content-Type": "image/png",
                "Content-Length": str(feishu_static_card._MAX_REMOTE_IMAGE_BYTES + 1),
            }
        ),
    )

    assert _channel()._upload_image_url(PUBLIC_URL, "token") is None
    assert uploaded.calls == []


def test_a_local_file_url_still_reads_from_disk(tmp_path, uploaded, monkeypatch):
    """``file://`` never touched the network and must keep working."""
    source = tmp_path / "local.png"
    source.write_bytes(b"local-bytes")

    assert _channel()._upload_image_url("file://" + str(source), "token") == "img_v2_chart"

    # The local branch streams the open file straight into the multipart body,
    # which is why the payload is not bytes.
    assert uploaded.calls[0]["files"]["image"].name == str(source)
