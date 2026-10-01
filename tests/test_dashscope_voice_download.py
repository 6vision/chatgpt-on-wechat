# encoding:utf-8
"""Bounded-download guard for ``DashScopeVoice._download_audio``.

Regression guard: before the size-capped downloader was wired in,
``_download_audio`` buffered ``resp.content`` with no upper bound, so a hostile
or broken TTS audio URL could fill disk. The downloader now raises
``MediaTooLargeError`` past the cap, which the method degrades from (returns
None) like any other download failure.
"""
import requests
from common.media_download import MAX_FILE_BYTES
from unittest.mock import MagicMock, patch

from voice.dashscope.dashscope_voice import DashScopeVoice


def test_download_audio_rejects_oversized_body():
    url = "http://example.test/audio.mp3"
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    # content is set only so the *old* code path (which wrote resp.content)
    # can complete without a TypeError; the size-capped downloader aborts on
    # the Content-Length pre-check before reading the stream.
    resp.content = b""
    resp.headers = {"Content-Length": str(MAX_FILE_BYTES + 1)}
    resp.close.return_value = None

    with patch.object(requests, "get", return_value=resp):
        # On an oversized response the method must degrade to None rather than
        # writing an unbounded body to disk.
        assert DashScopeVoice._download_audio(url) is None
