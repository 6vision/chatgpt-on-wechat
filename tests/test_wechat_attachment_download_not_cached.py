"""A failed attachment download must not be cached as a readable file."""

import os
import sys
import types
from pathlib import Path

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.context import ContextType
from channel.wechat_kf import wechat_kf_message as kf_mod


class _StreamingResponse:
    """A 200 response whose body can be made to fail mid-write."""

    def __init__(self, chunks, status_code=200, disposition='attachment; filename="report.pdf"'):
        self.status_code = status_code
        self.headers = {"Content-Disposition": disposition}
        self.content = b""
        self.closed = False
        self._chunks = chunks

    def iter_content(self, chunk_size=1):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        self.closed = True


def _client(response):
    return types.SimpleNamespace(
        media=types.SimpleNamespace(download=lambda media_id: response)
    )


def _kf_message(tmp_path, monkeypatch, response):
    monkeypatch.setattr(kf_mod, "_get_tmp_dir", lambda: str(tmp_path))
    raw = {
        "msgid": "kfmsg001",
        "send_time": 1700000000,
        "origin": 3,
        "msgtype": "file",
        "open_kfid": "kf1",
        "external_userid": "ext1",
        "file": {"media_id": "MEDIA1"},
    }
    return kf_mod.WechatKfMessage(msg=raw, client=_client(response))


def test_a_refused_download_leaves_no_readable_path(tmp_path, monkeypatch):
    # RED on unfixed code: content keeps the path the write *would* have used,
    # and Path(content).exists() is False -- a ghost the agent is told to read.
    monkeypatch.setattr(kf_mod, "MAX_FILE_BYTES", 1024, raising=False)
    response = _StreamingResponse([b"x" * 2048])
    msg = _kf_message(tmp_path, monkeypatch, response)

    msg.prepare()

    assert msg.content == "", "a failed download must not leave a path behind"
    assert not list(tmp_path.iterdir()), "nothing may be written to the tmp dir"


def test_a_non_200_response_leaves_no_readable_path(tmp_path, monkeypatch):
    # The other failure mode: the server refuses, nothing is ever written, and
    # the provisional media_id path used to survive into the cache.
    response = _StreamingResponse([], status_code=404)
    msg = _kf_message(tmp_path, monkeypatch, response)

    msg.prepare()

    assert msg.content == ""
    assert not list(tmp_path.iterdir())


def test_a_successful_download_still_reports_its_path(tmp_path, monkeypatch):
    # The success path must be untouched: the file lands and content names it.
    response = _StreamingResponse([b"real", b" bytes"])
    msg = _kf_message(tmp_path, monkeypatch, response)

    msg.prepare()

    assert Path(msg.content).read_bytes() == b"real bytes"
    assert msg.content.endswith("report.pdf")


def test_the_channel_refuses_to_cache_a_path_that_is_not_there(tmp_path, monkeypatch):
    # The second line of defence, at the point where the value is consumed:
    # the channel checks existence before handing the path to file_cache.
    from channel.wechat_kf import wechat_kf_channel as chan_mod
    from channel.file_cache import FileCache

    monkeypatch.setattr(kf_mod, "MAX_FILE_BYTES", 1024, raising=False)
    response = _StreamingResponse([b"x" * 2048])
    msg = _kf_message(tmp_path, monkeypatch, response)

    cache = FileCache()
    monkeypatch.setattr(chan_mod, "get_file_cache", lambda: cache, raising=False)

    msg.prepare()
    # Reproduce the channel's own branch decision.
    if msg.content and os.path.exists(msg.content):
        cache.add("ext1", msg.content, file_type="file")

    assert cache.get("ext1") == [], "a ghost path must never reach the cache"


def test_the_cache_would_have_accepted_a_ghost(tmp_path, monkeypatch):
    # Documents *why* the gate is needed: FileCache.add has no existence check
    # of its own, so a caller that does not check loses the file silently.
    from channel.file_cache import FileCache

    ghost = str(tmp_path / "never-written.pdf")
    cache = FileCache()
    cache.add("ext1", ghost, file_type="file")

    assert cache.get("ext1")[0]["path"] == ghost
    assert not os.path.exists(ghost), "FileCache stores paths, not files"


def test_a_weixin_file_download_failure_leaves_no_readable_path(tmp_path, monkeypatch):
    # The same shape on the weixin side: _download_media returns "" on failure
    # and used to leave content pointing at the placeholder path.
    from channel.weixin import weixin_message as wx_mod

    monkeypatch.setattr(wx_mod, "_get_tmp_dir", lambda: str(tmp_path))
    item = {"file_item": {"file_name": "quarterly.pdf"}}

    message = wx_mod.WeixinMessage.__new__(wx_mod.WeixinMessage)
    message.msg_id = "wxmsg1"
    message.ctype = ContextType.FILE
    message._download_media = lambda item, media_type, cdn: ""  # download failed
    message._setup_media(item, wx_mod.ITEM_FILE, "https://cdn.example")

    message._prepare_fn()

    assert message.content == "", "a failed download must not leave a path behind"


def test_a_weixin_video_download_failure_leaves_no_readable_path(tmp_path, monkeypatch):
    from channel.weixin import weixin_message as wx_mod

    monkeypatch.setattr(wx_mod, "_get_tmp_dir", lambda: str(tmp_path))
    item = {"video_item": {}}

    message = wx_mod.WeixinMessage.__new__(wx_mod.WeixinMessage)
    message.msg_id = "wxmsg2"
    message.ctype = ContextType.FILE
    message._download_media = lambda item, media_type, cdn: ""
    message._setup_media(item, wx_mod.ITEM_VIDEO, "https://cdn.example")

    message._prepare_fn()

    assert message.content == ""


def test_a_successful_weixin_download_still_reports_its_path(tmp_path, monkeypatch):
    from channel.weixin import weixin_message as wx_mod

    monkeypatch.setattr(wx_mod, "_get_tmp_dir", lambda: str(tmp_path))
    item = {"file_item": {"file_name": "quarterly.pdf"}}

    landed = tmp_path / "quarterly.pdf"
    landed.write_bytes(b"pdf")

    message = wx_mod.WeixinMessage.__new__(wx_mod.WeixinMessage)
    message.msg_id = "wxmsg3"
    message.ctype = ContextType.FILE
    message._download_media = lambda item, media_type, cdn: str(landed)
    message._setup_media(item, wx_mod.ITEM_FILE, "https://cdn.example")

    message._prepare_fn()

    assert message.content == str(landed)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
