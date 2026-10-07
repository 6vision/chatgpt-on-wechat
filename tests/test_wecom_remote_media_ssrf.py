"""WeCom fetches reply media through the guarded download."""

from channel.wecom_bot import wecom_bot_channel as channel
from common.media_download import DownloadResult


def test_reply_media_download_is_guarded(monkeypatch, tmp_path):
    seen = {}

    def download_to_file(url, path, max_bytes, **kwargs):
        seen.update(kwargs)
        with open(path, "wb") as f:
            f.write(b"media")
        return DownloadResult(5, "image/png")

    monkeypatch.setattr(channel, "download_to_file", download_to_file)
    monkeypatch.setattr(channel, "_media_tmp_path", lambda prefix, ext="": str(tmp_path / prefix))
    channel._download_remote_media("https://example.test/a.png", "wecom_img", None, 100, 30)
    assert seen.get("guarded") is True
