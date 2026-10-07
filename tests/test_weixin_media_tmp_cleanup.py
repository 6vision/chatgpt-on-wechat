# encoding:utf-8
"""A media reply must not leave its download behind on the weixin channel.

``WeixinChannel._resolve_media_path`` downloads a reply's media into the
managed tmp dir (``state_dir.tmp_dir()``, via ``_media_tmp_path``) so
``upload_media_to_cdn`` has a local file to read. Nothing ever removed those
files afterwards: the class contains no ``os.remove`` for media, and no other
component prunes that directory. Every reply carrying a URL therefore added a
file that stayed for the life of the install.

The feishu channel already does the cleanup this one is missing -- three
``finally:`` blocks around its own downloads in ``feishu_channel.py`` (`:2052`,
`:2112`, and the audio staging note at `:2179`) -- so the two channels were
handling the same action two different ways.

The other half is not deleting the wrong thing. A reply may also point at a
file the user owns, and that has to survive the send, so the senders ask
whether the path was downloaded before removing it.
"""

import os
import sys
import uuid

import pytest

from channel.weixin import weixin_channel as wc

Channel = getattr(wc.WeixinChannel, "__wrapped__", wc.WeixinChannel)


class _Response:
    """Minimal stand-in for the streamed response ``save_response`` consumes."""

    def __init__(self, content_type="image/png", payload=b"\x89PNG\r\n\x1a\nbody"):
        self.headers = {"Content-Type": content_type}
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        yield self._payload

    def close(self):
        return None


@pytest.fixture
def media(tmp_path, monkeypatch):
    """Point ``_media_tmp_path`` at this test's dir and stub the network."""
    downloads = []

    def fake_get(url, **kwargs):
        downloads.append(url)
        return _Response()

    monkeypatch.setattr(wc, "requests",
                        type("R", (), {"get": staticmethod(fake_get)}))
    monkeypatch.setattr(
        wc, "_media_tmp_path",
        lambda prefix, ext="": str(tmp_path / f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"),
    )
    return tmp_path, downloads


def _channel(tmp_path):
    """A channel instance with just enough surface for the media senders."""
    channel = Channel.__new__(Channel)
    channel._sent_text = []
    channel._send_text = lambda text, receiver, token: channel._sent_text.append(text)
    channel._check_send_response = lambda resp, receiver: None
    channel.api = _FakeApi()
    return channel


class _FakeApi:
    def __init__(self):
        self.uploaded = []

    def send_image_item(self, **kw):
        return {"ret": 0}

    def send_file_item(self, **kw):
        return {"ret": 0}

    def send_video_item(self, **kw):
        return {"ret": 0}


@pytest.fixture
def uploads(monkeypatch):
    """Capture what the CDN upload was handed, and read the file while it exists."""
    seen = []

    def fake_upload(api, local_path, receiver, media_type=1):
        # The upload reads the file, so prove it is really there and complete.
        seen.append((local_path, open(local_path, "rb").read()))
        return {
            "encrypt_query_param": "q",
            "aes_key_b64": "k",
            "ciphertext_size": 99,
            "raw_size": len(seen[-1][1]),
        }

    monkeypatch.setattr(wc, "upload_media_to_cdn", fake_upload)
    return seen


# --- a download must not outlive the send --------------------------------

def test_a_downloaded_image_is_gone_after_the_send(media, uploads):
    tmp_path, _ = media
    channel = _channel(tmp_path)

    channel._send_image("https://example.test/shot.png", "bob", "tok")

    assert uploads, "nothing was uploaded"
    assert not os.path.exists(uploads[0][0]), "the download stayed on disk"
    assert not list(tmp_path.iterdir()), list(tmp_path.iterdir())


def test_a_downloaded_file_is_gone_after_the_send(media, uploads):
    tmp_path, _ = media
    channel = _channel(tmp_path)

    channel._send_file("https://example.test/report.pdf", "bob", "tok")

    assert uploads
    assert not os.path.exists(uploads[0][0])
    assert not list(tmp_path.iterdir())


def test_a_downloaded_video_is_gone_after_the_send(media, uploads):
    tmp_path, _ = media
    channel = _channel(tmp_path)

    channel._send_video("https://example.test/clip.mp4", "bob", "tok")

    assert uploads
    assert not os.path.exists(uploads[0][0])
    assert not list(tmp_path.iterdir())


def test_the_upload_still_sees_the_whole_file(media, uploads):
    """The cleanup must run after the upload, never before it."""
    tmp_path, downloads = media
    channel = _channel(tmp_path)

    channel._send_image("https://example.test/shot.png", "bob", "tok")

    local_path, payload = uploads[0]
    assert payload == b"\x89PNG\r\n\x1a\nbody"
    assert downloads == ["https://example.test/shot.png"]


# --- a file the user owns must survive -----------------------------------

def test_a_local_path_the_user_asked_for_is_not_deleted(media, uploads):
    tmp_path, _ = media
    owned = tmp_path / "mine.png"
    owned.write_bytes(b"the users own file")
    channel = _channel(tmp_path)

    channel._send_image(str(owned), "bob", "tok")

    assert uploads[0][0] == str(owned)
    assert owned.read_bytes() == b"the users own file", "deleted a user file"


def test_a_local_file_url_the_user_asked_for_is_not_deleted(media, uploads):
    tmp_path, _ = media
    owned = tmp_path / "mine.png"
    owned.write_bytes(b"the users own file")
    channel = _channel(tmp_path)

    channel._send_image("file://" + str(owned), "bob", "tok")

    assert owned.exists(), "deleted a user file named as a file:// URL"


def test_a_local_file_survives_the_file_sender_too(media, uploads):
    tmp_path, _ = media
    owned = tmp_path / "notes.txt"
    owned.write_bytes(b"notes")
    channel = _channel(tmp_path)

    channel._send_file(str(owned), "bob", "tok")

    assert owned.exists()


# --- the failure paths are where leaks usually hide ----------------------

def test_the_download_is_removed_when_the_upload_raises(media, monkeypatch):
    tmp_path, _ = media

    def boom(*a, **kw):
        raise OSError("cdn down")

    monkeypatch.setattr(wc, "upload_media_to_cdn", boom)
    channel = _channel(tmp_path)

    channel._send_image("https://example.test/shot.png", "bob", "tok")

    assert not list(tmp_path.iterdir()), "a failed send leaked the download"


def test_the_download_is_removed_when_the_send_api_raises(media, monkeypatch):
    tmp_path, _ = media
    monkeypatch.setattr(wc, "upload_media_to_cdn",
                        lambda *a, **kw: {
                            "encrypt_query_param": "q", "aes_key_b64": "k",
                            "ciphertext_size": 1, "raw_size": 1})
    channel = _channel(tmp_path)
    channel.api = _BrokenApi()

    channel._send_image("https://example.test/shot.png", "bob", "tok")

    assert not list(tmp_path.iterdir()), "a failed send leaked the download"
    # The failure is still reported to the user, not swallowed.
    assert channel._sent_text == ["[Image send failed]"]


class _BrokenApi(_FakeApi):
    def send_image_item(self, **kw):
        raise RuntimeError("session expired")


def test_a_missing_remote_file_leaves_nothing_behind(media, monkeypatch):
    tmp_path, _ = media

    def boom(url, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(wc, "requests",
                        type("R", (), {"get": staticmethod(boom)}))
    channel = _channel(tmp_path)

    # Nothing to download and nothing local: no file should appear.
    assert channel._resolve_media("https://example.test/gone.png") == ("", False)
    assert not list(tmp_path.iterdir())


def test_an_empty_reply_resolves_to_nothing(media):
    tmp_path, _ = media
    channel = _channel(tmp_path)

    assert channel._resolve_media("") == ("", False)
    assert not list(tmp_path.iterdir())


# --- repeated replies must not accumulate --------------------------------

def test_many_media_replies_leave_nothing_behind(media, uploads):
    tmp_path, _ = media
    channel = _channel(tmp_path)

    for i in range(5):
        channel._send_image("https://example.test/%d.png" % i, "bob", "tok")

    assert len(uploads) == 5
    assert not list(tmp_path.iterdir()), [p.name for p in tmp_path.iterdir()]


# --- the helper itself ---------------------------------------------------

def test_removing_a_missing_file_is_not_an_error(tmp_path):
    wc._remove_media_tmp(str(tmp_path / "never-existed.png"))
    wc._remove_media_tmp("")


def test_the_temporary_path_helper_uses_the_managed_tmp_dir():
    """Guard the premise: these files land in the workspace's tmp dir."""
    from common import state_dir

    path = wc._media_tmp_path("wx_media", ".png")
    assert str(state_dir.tmp_dir()) in path
    assert path.endswith(".png")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))