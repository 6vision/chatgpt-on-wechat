# encoding:utf-8
"""Weixin media senders remove their own downloads but never a user's local file."""

import os
import uuid

import pytest

from channel.weixin import weixin_channel as wc

Channel = getattr(wc.WeixinChannel, "__wrapped__", wc.WeixinChannel)
PAYLOAD = b"\x89PNG\r\n\x1a\nbody"
UPLOADED = {"encrypt_query_param": "q", "aes_key_b64": "k", "ciphertext_size": 1, "raw_size": 1}


class _Response:
    headers = {"Content-Type": "image/png"}
    status_code = 200

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        yield PAYLOAD

    def close(self):
        return None


def _ok(*a, **kw):
    return {"ret": 0}


def _raise(*a, **kw):
    raise OSError("boom")


def _stub_get(monkeypatch, get):
    monkeypatch.setattr(wc, "requests", type("R", (), {"get": staticmethod(get)}))


@pytest.fixture
def channel(tmp_path, monkeypatch):
    _stub_get(monkeypatch, lambda url, **kw: _Response())
    monkeypatch.setattr(wc.state_dir, "tmp_file",
                        lambda prefix, ext="": str(tmp_path / f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"))
    ch = Channel.__new__(Channel)
    ch._sent_text = []
    ch._send_text = lambda text, receiver, token: ch._sent_text.append(text)
    ch._check_send_response = lambda resp, receiver: None
    ch.api = type("Api", (), {})()
    ch.api.send_image_item = ch.api.send_file_item = ch.api.send_video_item = _ok
    return ch


@pytest.fixture
def uploads(monkeypatch):
    seen = []

    def fake_upload(api, local_path, receiver, media_type=1):
        seen.append((local_path, open(local_path, "rb").read()))
        return UPLOADED

    monkeypatch.setattr(wc, "upload_media_to_cdn", fake_upload)
    return seen


@pytest.mark.parametrize("sender", ["_send_image", "_send_file", "_send_video"])
def test_download_is_removed_after_upload_saw_full_file(channel, uploads, tmp_path, sender):
    for i in range(3):
        getattr(channel, sender)("https://example.test/%d.bin" % i, "bob", "tok")

    assert [payload for _, payload in uploads] == [PAYLOAD] * 3
    assert not any(os.path.exists(path) for path, _ in uploads)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("sender,prefix", [("_send_image", ""), ("_send_image", "file://"), ("_send_file", "")])
def test_user_owned_local_file_is_kept(channel, uploads, tmp_path, sender, prefix):
    owned = tmp_path / "mine.png"
    owned.write_bytes(b"the users own file")

    getattr(channel, sender)(prefix + str(owned), "bob", "tok")

    assert owned.read_bytes() == b"the users own file"


@pytest.mark.parametrize("broken", ["upload", "send"])
def test_download_is_removed_when_send_fails(channel, tmp_path, monkeypatch, broken):
    monkeypatch.setattr(wc, "upload_media_to_cdn", _raise if broken == "upload" else lambda *a, **kw: UPLOADED)
    if broken == "send":
        channel.api.send_image_item = _raise

    channel._send_image("https://example.test/shot.png", "bob", "tok")

    assert not list(tmp_path.iterdir())
    if broken == "send":
        assert channel._sent_text == ["[Image send failed]"]


def test_unresolvable_media_leaves_nothing_behind(channel, tmp_path, monkeypatch):
    assert channel._resolve_media("") == ("", False)
    _stub_get(monkeypatch, _raise)
    assert channel._resolve_media("https://example.test/gone.png") == ("", False)
    assert not list(tmp_path.iterdir())

