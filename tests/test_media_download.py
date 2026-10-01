"""Shared size-capped media downloads and the callers built on them."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from agent.tools.vision import vision as vision_mod
from bridge.reply import ReplyType
from common import media_download
from common.media_download import (
    MAX_FILE_BYTES,
    MAX_IMAGE_BYTES,
    MediaTooLargeError,
    download_bytes,
    download_to_file,
    read_response,
    save_response,
)
from voice.ali import ali_api
from voice.custom.custom_voice import CustomVoice
from voice.linkai import linkai_voice
from voice.minimax import minimax_voice
from voice.openai import openai_voice
from voice.zhipuai import zhipuai_voice


class Response:
    def __init__(self, chunks=(b"media",), headers=None, status_code=200, interrupt=False):
        self.chunks = chunks
        self.headers = headers or {}
        self.status_code = status_code
        self.interrupt = interrupt
        self.closed = False
        self.iterated = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        self.iterated = True
        for chunk in self.chunks:
            yield chunk
            if self.interrupt:
                raise OSError("connection lost")

    def close(self):
        self.closed = True


class SseResponse:
    """The shape MiniMax needs: raw SSE lines instead of one body."""

    def __init__(self, lines, headers=None, status_code=200):
        self.lines = lines
        self.headers = headers or {}
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_lines(self):
        yield from self.lines

    def close(self):
        self.closed = True


@pytest.fixture
def serve(monkeypatch):
    calls = []

    def install(response):
        def get(url, **kwargs):
            calls.append(dict(kwargs, url=url))
            return response

        monkeypatch.setattr(media_download.requests, "get", get)
        return calls

    return install


def test_file_is_streamed_into_place(tmp_path, serve):
    response = Response(chunks=(b"ab", b"", b"cd"), headers={"Content-Type": "image/png"})
    calls = serve(response)
    target = tmp_path / "out.png"

    result = download_to_file("https://example.test/a", str(target), 10, timeout=7, headers={"X": "1"})

    assert target.read_bytes() == b"abcd"
    assert result == (4, "image/png")
    assert calls == [{"url": "https://example.test/a", "stream": True, "timeout": 7, "headers": {"X": "1"}}]
    assert list(tmp_path.iterdir()) == [target]
    assert response.closed


def test_declared_oversize_is_rejected_before_reading(tmp_path, serve):
    response = Response(headers={"Content-Length": "11"})
    serve(response)

    with pytest.raises(MediaTooLargeError):
        download_to_file("https://example.test/a", str(tmp_path / "out"), 10)

    assert not response.iterated
    assert list(tmp_path.iterdir()) == []
    assert response.closed


def test_malformed_content_length_still_hits_streamed_cap(tmp_path, serve):
    response = Response(chunks=(b"123456", b"789012"), headers={"Content-Length": "abc"})
    serve(response)

    with pytest.raises(MediaTooLargeError):
        download_to_file("https://example.test/a", str(tmp_path / "out"), 10)

    assert list(tmp_path.iterdir()) == []
    assert response.closed


@pytest.mark.parametrize("response", [
    Response(status_code=404),
    Response(chunks=(b"partial", b"rest"), interrupt=True),
    Response(chunks=(b"123456", b"789012")),
])
def test_failure_keeps_existing_file_and_leaves_no_temp(tmp_path, serve, response):
    serve(response)
    target = tmp_path / "out"
    target.write_bytes(b"previous")

    with pytest.raises((requests.HTTPError, OSError, MediaTooLargeError)):
        download_to_file("https://example.test/a", str(target), 10)

    assert target.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [target]
    assert response.closed


def test_bytes_download_is_capped(serve):
    ok = Response(chunks=(b"ab", b"cd"))
    serve(ok)
    assert download_bytes("https://example.test/a", 4) == b"abcd"
    assert ok.closed

    too_big = Response(chunks=(b"ab", b"cde"))
    serve(too_big)
    with pytest.raises(MediaTooLargeError):
        download_bytes("https://example.test/a", 4)
    assert too_big.closed


def test_max_seconds_stops_a_trickling_download(serve, monkeypatch):
    response = Response(chunks=(b"ab", b"cd"))
    calls = serve(response)
    clock = iter([0, 1, 61])
    monkeypatch.setattr(media_download, "time", SimpleNamespace(monotonic=lambda: next(clock)))

    with pytest.raises(requests.Timeout):
        download_bytes("https://example.test/a", 10, max_seconds=60)

    assert "max_seconds" not in calls[0]
    assert response.closed


def test_bytes_download_raises_on_http_error(serve):
    response = Response(status_code=500)
    serve(response)

    with pytest.raises(requests.HTTPError):
        download_bytes("https://example.test/a")

    assert not response.iterated
    assert response.closed


# ── a response the caller already holds ───────────────────────────────


def test_save_response_streams_an_open_response_into_place(tmp_path):
    response = Response(chunks=(b"ab", b"cd"), headers={"Content-Type": "audio/mpeg"})
    target = tmp_path / "reply.mp3"

    result = save_response(response, str(target), 10)

    assert target.read_bytes() == b"abcd"
    assert result == (4, "audio/mpeg")
    assert list(tmp_path.iterdir()) == [target]
    assert response.closed


def test_save_response_refuses_an_oversized_body_and_keeps_the_old_file(tmp_path):
    response = Response(chunks=(b"123456", b"789012"))
    target = tmp_path / "reply.mp3"
    target.write_bytes(b"previous")

    with pytest.raises(MediaTooLargeError):
        save_response(response, str(target), 10)

    assert target.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [target]
    assert response.closed


def test_read_response_returns_the_body_and_closes_the_response():
    response = Response(chunks=(b"ab", b"cd"))

    assert read_response(response, 4) == b"abcd"
    assert response.closed


def test_read_response_refuses_an_oversized_body():
    response = Response(chunks=(b"123456", b"789012"))

    with pytest.raises(MediaTooLargeError):
        read_response(response, 10)

    assert response.closed


# ── the callers that used to open-code the same loop ──────────────────


def _oversized(limit):
    """A body that is over *limit* in a single chunk.

    ``_read_chunks`` counts a chunk before yielding it, so the cap trips with
    nothing written to disk and no partial file to clean up.
    """
    return [b"x" * (limit + 1)]


def test_custom_tts_refuses_an_oversized_body():
    response = Response(chunks=_oversized(MAX_FILE_BYTES), headers={"Content-Type": "audio/mpeg"})

    with patch("voice.custom.custom_voice.requests.post", return_value=response), \
            patch("voice.custom.custom_voice.conf") as conf, \
            patch.object(CustomVoice, "_resolve_credentials",
                         return_value=("key", "https://vendor.test")):
        conf.return_value = {"text_to_voice_model": "fun-tts-large", "tts_voice_id": "anna"}
        reply = CustomVoice("custom").textToVoice("hello")

    assert reply.type == ReplyType.ERROR
    assert response.closed


def test_openai_tts_refuses_an_oversized_body():
    response = Response(chunks=_oversized(MAX_FILE_BYTES), headers={"Content-Type": "audio/mpeg"})

    with patch("voice.openai.openai_voice.conf") as conf, \
            patch("voice.openai.openai_voice.requests.post", return_value=response):
        conf.return_value = {"open_ai_api_key": "sk-test"}
        reply = openai_voice.OpenaiVoice().textToVoice("hello")

    assert reply.type == ReplyType.ERROR
    assert response.closed


def test_linkai_tts_refuses_an_oversized_body():
    response = Response(chunks=_oversized(MAX_FILE_BYTES), headers={"Content-Type": "audio/mpeg"})

    with patch.object(linkai_voice, "conf", lambda: {"linkai_api_key": "k"}), \
            patch.object(linkai_voice, "apply_client_source", lambda h: h), \
            patch.object(linkai_voice, "apply_cloud_user", lambda h: h), \
            patch.object(linkai_voice.requests, "post", return_value=response):
        reply = linkai_voice.LinkAIVoice().textToVoice("hello")

    assert reply.type == ReplyType.ERROR
    assert response.iterated
    assert response.closed


def test_zhipuai_tts_refuses_an_oversized_body():
    # ZhipuAI caps a body at the same 25 MiB its ASR path allows per file.
    response = Response(chunks=_oversized(zhipuai_voice.MAX_FILE_BYTES),
                        headers={"Content-Type": "audio/wav"})

    with patch.object(zhipuai_voice, "conf", lambda: {"zhipu_ai_api_key": "k"}), \
            patch.object(zhipuai_voice.requests, "post", return_value=response):
        reply = zhipuai_voice.ZhipuAIVoice().textToVoice("hello")

    assert reply.type == ReplyType.ERROR
    assert response.iterated
    assert response.closed


def test_ali_tts_refuses_an_oversized_body():
    response = Response(chunks=_oversized(MAX_FILE_BYTES), headers={"Content-Type": "audio/mpeg"})

    with patch.object(ali_api.requests, "post", return_value=response):
        written = ali_api.text_to_speech_aliyun(
            "https://example.test/tts", "你好", "appkey", "token"
        )

    assert written is None
    assert response.iterated
    assert response.closed


def test_vision_refuses_an_oversized_image():
    response = Response(chunks=_oversized(MAX_IMAGE_BYTES), headers={"Content-Type": "image/png"})

    with patch.object(vision_mod, "safe_get", lambda *args, **kwargs: response):
        with pytest.raises(vision_mod.VisionAPIError):
            vision_mod.Vision._download_to_data_url("https://example.test/a.png")

    assert response.closed


def test_minimax_tts_refuses_an_oversized_stream():
    # MiniMax delivers the audio as SSE frames, so it cannot call the helpers;
    # it still honours the shared cap. The limit is patched small so the frame
    # stays tiny while the decoded audio is already over it.
    frame = b"data: " + json.dumps({"data": {"audio": "41" * 5}}).encode()
    response = SseResponse([frame])

    with patch.object(minimax_voice.requests, "post", return_value=response), \
            patch.object(minimax_voice, "MAX_FILE_BYTES", 4), \
            patch.object(minimax_voice, "conf", lambda: {"minimax_api_key": "k"}):
        reply = minimax_voice.MinimaxVoice().textToVoice("hello")

    assert reply.type == ReplyType.ERROR
    assert response.closed
