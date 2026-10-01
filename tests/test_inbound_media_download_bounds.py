"""Inbound attachments (``media_id`` -> local file) must be streamed and capped.

Every channel that receives an attachment pulls it from the platform by
``media_id``. The *sending* side of wechatmp / wechat_kf already streams a
remote reply URL and refuses an oversized body
(``test_wechatmp_remote_media_bounds`` / ``test_wechat_kf_remote_media``), and
the other inbound paths -- feishu, dingtalk, qq, slack -- already go through
``common.media_download``. The call sites here did not: the three
``*_message`` adapters ran ``client.media.download(media_id)`` and wrote
``response.content`` straight to disk, and ``weixin_api`` decrypted
``resp.content`` in one piece. Each of them buffered a body of any size into
memory whole and then wrote it with no cap.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from bridge.context import ContextType
from channel.wechat_kf import wechat_kf_message as kf_mod
from channel.wechatcom import wechatcomapp_message as wechatcom_mod
from channel.wechatmp import wechatmp_message as wechatmp_mod
from channel.weixin import weixin_api
from common.media_download import MediaTooLargeError

MEDIA_ID = "3rDPHxBQtdWeQLzxwpT-HNYw2eXba7ma9lQc"


class _StreamingResponse:
    """A platform media download that only offers the streaming API.

    ``.content`` raises instead of answering, so a caller that still buffers
    the whole body fails the test rather than quietly passing it.
    """

    def __init__(self, chunks, *, status_code=200, headers=None):
        self._chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    @property
    def content(self):
        raise AssertionError("inbound media must stream instead of buffering .content")

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def close(self):
        self.closed = True


class _FakeMedia:
    def __init__(self, response):
        self._response = response

    def download(self, media_id):
        return self._response


def _client(response):
    return SimpleNamespace(media=_FakeMedia(response))


# ── wechatcomapp ──────────────────────────────────────────────────────
def _wechatcom(tmp_path, monkeypatch, response, msg_type):
    monkeypatch.setattr(
        wechatcom_mod, "TmpDir", lambda: SimpleNamespace(path=lambda: str(tmp_path) + "/")
    )
    raw = SimpleNamespace(
        id="msg-1",
        time=1700000000,
        type=msg_type,
        content="",
        format="amr",
        media_id=MEDIA_ID,
        source="user",
        target="bot",
    )
    return wechatcom_mod.WechatComAppMessage(msg=raw, client=_client(response))


@pytest.mark.parametrize("msg_type", ["voice", "image"])
def test_wechatcom_inbound_media_is_streamed_into_place(tmp_path, monkeypatch, msg_type):
    response = _StreamingResponse([b"media", b" payload"])
    msg = _wechatcom(tmp_path, monkeypatch, response, msg_type)

    msg.prepare()

    assert Path(msg.content).read_bytes() == b"media payload"
    assert response.closed, "the download must be closed once it is written"


def test_wechatcom_refuses_an_oversized_image_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(wechatcom_mod, "MAX_IMAGE_BYTES", 1024, raising=False)
    response = _StreamingResponse([b"x" * 2048])
    msg = _wechatcom(tmp_path, monkeypatch, response, "image")

    msg.prepare()

    assert not Path(msg.content).exists(), "an oversized body must not reach the tmp dir"
    assert response.closed


# ── wechatmp ──────────────────────────────────────────────────────────
def _wechatmp(tmp_path, monkeypatch, response, msg_type):
    monkeypatch.setattr(
        wechatmp_mod, "TmpDir", lambda: SimpleNamespace(path=lambda: str(tmp_path) + "/")
    )
    raw = SimpleNamespace(
        id="msg-1",
        time=1700000000,
        type=msg_type,
        content="",
        format="amr",
        media_id=MEDIA_ID,
        recognition=None,
        source="user",
        target="bot",
    )
    return wechatmp_mod.WeChatMPMessage(msg=raw, client=_client(response))


@pytest.mark.parametrize("msg_type", ["voice", "image"])
def test_wechatmp_inbound_media_is_streamed_into_place(tmp_path, monkeypatch, msg_type):
    response = _StreamingResponse([b"media", b" payload"])
    msg = _wechatmp(tmp_path, monkeypatch, response, msg_type)

    msg.prepare()

    assert Path(msg.content).read_bytes() == b"media payload"
    assert response.closed


def test_wechatmp_refuses_an_oversized_voice_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(wechatmp_mod, "MAX_FILE_BYTES", 1024, raising=False)
    response = _StreamingResponse([b"x" * 2048])
    msg = _wechatmp(tmp_path, monkeypatch, response, "voice")

    msg.prepare()

    assert not Path(msg.content).exists()
    assert response.closed


# ── wechat_kf ─────────────────────────────────────────────────────────
def _wechat_kf(tmp_path, monkeypatch, response, msgtype):
    monkeypatch.setattr(kf_mod, "_get_tmp_dir", lambda: str(tmp_path))
    raw = {
        "msgid": "kfmsg001",
        "send_time": 1700000000,
        "origin": 3,
        "msgtype": msgtype,
        "open_kfid": "kf1",
        "external_userid": "ext1",
        msgtype: {"media_id": MEDIA_ID},
    }
    return kf_mod.WechatKfMessage(msg=raw, client=_client(response))


@pytest.mark.parametrize(
    "msgtype,ctype",
    [("image", ContextType.IMAGE), ("voice", ContextType.VOICE), ("file", ContextType.FILE)],
)
def test_wechat_kf_inbound_media_is_streamed_into_place(tmp_path, monkeypatch, msgtype, ctype):
    response = _StreamingResponse([b"media", b" payload"])
    msg = _wechat_kf(tmp_path, monkeypatch, response, msgtype)

    msg.prepare()

    assert msg.ctype == ctype
    assert Path(msg.content).read_bytes() == b"media payload"
    assert Path(msg.content).parent == tmp_path
    assert response.closed


def test_wechat_kf_refuses_an_oversized_file_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(kf_mod, "MAX_FILE_BYTES", 1024, raising=False)
    response = _StreamingResponse([b"x" * 2048])
    msg = _wechat_kf(tmp_path, monkeypatch, response, "file")

    msg.prepare()

    assert not Path(msg.content).exists()
    assert not list(tmp_path.glob(".download_*")), "no temp file may be left behind"
    assert response.closed


# ── weixin CDN ────────────────────────────────────────────────────────
def _aes_ecb_encrypt(payload, key):
    """PKCS#7-pad and encrypt, mirroring what the CDN hands back."""
    from Crypto.Cipher import AES

    pad = 16 - len(payload) % 16
    return AES.new(key, AES.MODE_ECB).encrypt(payload + bytes([pad]) * pad)


class _CdnSession:
    def __init__(self, response):
        self._response = response

    def get(self, *args, **kwargs):
        return self._response


def _cdn_download(tmp_path, monkeypatch, response, aes_key):
    monkeypatch.setattr(weixin_api, "_get_cdn_session", lambda: _CdnSession(response))
    return weixin_api.download_media_from_cdn(
        "https://cdn.example.com", "encrypted-param", aes_key, str(tmp_path / "media.bin")
    )


def test_weixin_cdn_body_is_streamed_before_it_is_decrypted(tmp_path, monkeypatch):
    key = bytes(range(16))
    response = _StreamingResponse([_aes_ecb_encrypt(b"payload", key)])

    save_path = _cdn_download(tmp_path, monkeypatch, response, key.hex())

    assert Path(save_path).read_bytes() == b"payload"
    assert response.closed


def test_weixin_cdn_refuses_an_oversized_body(tmp_path, monkeypatch):
    monkeypatch.setattr(weixin_api, "MAX_FILE_BYTES", 1024, raising=False)
    response = _StreamingResponse([b"x" * 2048])

    with pytest.raises(MediaTooLargeError):
        _cdn_download(tmp_path, monkeypatch, response, "00" * 16)

    assert not (tmp_path / "media.bin").exists()
    assert response.closed
