"""WeCom app file replies remove what they downloaded but never the caller's own file."""

import pytest

from bridge.reply import Reply, ReplyType
from channel.wechatcom import wechatcomapp_channel as mod


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(mod.state_dir, "tmp_dir", lambda: root)
    return root


@pytest.fixture
def channel(workspace, monkeypatch):
    cls = mod.WechatComAppChannel.__wrapped__
    handle = cls.__new__(cls)
    handle.agent_id = "agent-1"
    handle.sent, handle.uploads = [], []

    class _Message:
        @staticmethod
        def send_file(agent_id, receiver, media_id):
            handle.sent.append(("file", media_id))

        @staticmethod
        def send_video(agent_id, receiver, media_id):
            handle.sent.append(("video", media_id))

        @staticmethod
        def send_text(agent_id, receiver, text):
            handle.sent.append(("text", text))

    class _Media:
        @staticmethod
        def upload(media_type, payload):
            handle.uploads.append((media_type, payload[0]))
            return {"media_id": f"media-{len(handle.uploads)}"}

    handle.client = type("_Client", (), {"message": _Message, "media": _Media})()

    def _download(url, local, max_bytes, timeout=None, max_seconds=None):
        with open(local, "wb") as fh:
            fh.write(b"remote-body")

    monkeypatch.setattr(mod, "download_to_file", _download)
    return handle


def _leftovers(workspace):
    return sorted(p.name for p in workspace.iterdir())


@pytest.mark.parametrize("reply_type,url", [(ReplyType.FILE, "https://example.com/r.pdf"),
                                            (ReplyType.VIDEO, "https://example.com/clip.mp4")])
def test_a_remote_reply_leaves_nothing_behind(channel, workspace, reply_type, url):
    channel._send_file(Reply(reply_type, url), "user-1")

    assert channel.uploads
    assert _leftovers(workspace) == []


def test_upload_or_download_failure_still_cleans_up(channel, workspace, monkeypatch):
    def _upload_fails(media_type, payload):
        raise mod.WeChatClientException(-1, "nope")

    channel.client.media.upload = staticmethod(_upload_fails)
    channel._send_file(Reply(ReplyType.FILE, "https://example.com/r.pdf"), "user-1")
    assert _leftovers(workspace) == []

    def _download_fails(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(mod, "download_to_file", _download_fails)
    channel._send_file(Reply(ReplyType.FILE, "https://example.com/r.pdf"), "user-1")
    assert _leftovers(workspace) == []


@pytest.mark.parametrize("scheme", ["file://", ""])
def test_a_local_file_is_never_deleted(channel, workspace, scheme):
    mine = workspace / "produced-by-agent.pdf"
    mine.write_bytes(b"agent output")

    channel._send_file(Reply(ReplyType.FILE, f"{scheme}{mine}"), "user-1")

    assert mine.exists()
    assert channel.uploads


def test_the_resolver_reports_whether_it_downloaded(channel, workspace):
    path, downloaded = channel._resolve_media_path("https://example.com/r.pdf")
    assert downloaded == path

    mine = workspace / "mine.pdf"
    mine.write_bytes(b"x")
    assert channel._resolve_media_path(f"file://{mine}") == (str(mine), "")
    assert channel._resolve_media_path(str(workspace / "absent.pdf")) == ("", "")
