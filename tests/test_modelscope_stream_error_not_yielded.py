# encoding:utf-8
"""A mid-stream ModelScope failure must reach the consumer as an error chunk."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.modelscope.modelscope_bot import ModelScopeBot


def _dying_lines():
    yield b'data: {"choices": [{"delta": {"content": "partial"}}]}'
    raise OSError("connection reset by peer")


def test_mid_stream_failure_yields_error_chunk_after_partial_text():
    bot = ModelScopeBot.__new__(ModelScopeBot)
    bot.api_key, bot.base_url = "test-key", "http://localhost"
    session = MagicMock(messages=[{"role": "user", "content": "hi"}])
    response = MagicMock(status_code=200, text="")
    response.iter_lines.side_effect = _dying_lines
    with patch("models.modelscope.modelscope_bot.requests.post", return_value=response):
        chunks = list(bot._handle_stream_response(session, {"model": "Qwen/Qwen3-8B"}))

    assert chunks[0]["choices"][0]["delta"]["content"] == "partial"
    errors = [c for c in chunks if c.get("error")]
    assert len(errors) == 1
    assert errors[0]["status_code"] == 500
    assert "connection reset by peer" in str(errors[0]["message"])
