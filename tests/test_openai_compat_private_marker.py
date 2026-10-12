# encoding:utf-8
"""'_'-prefixed message markers are kept in conversion but stripped from the outgoing request."""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.openai import openai_http_client
from models.openai_compatible_bot import OpenAICompatibleBot

PARTS = [{"text": "hi", "thoughtSignature": "sig"}]
HISTORY = [
    {"role": "user", "content": "question"},
    {"role": "assistant", "content": [{"type": "text", "text": "answer"}], "_gemini_raw_parts": PARTS},
]


class _Bot(OpenAICompatibleBot):
    def get_api_config(self):
        return {"model": "gpt-4o", "api_key": "test-key", "api_base": "https://example.invalid/v1"}


def test_private_keys_are_not_sent():
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "model": "gpt-4o",
        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    with patch.object(openai_http_client.requests, "post", return_value=response) as post:
        _Bot().call_with_tools(HISTORY, tools=None, stream=False)
    messages = post.call_args.kwargs["json"]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert not [k for m in messages for k in m if k.startswith("_")]


def test_conversion_still_carries_the_marker():
    # Callers that bind their own call_with_tools rely on the converted marker.
    converted = _Bot()._convert_messages_to_openai_format(HISTORY)
    assert converted[-1]["_gemini_raw_parts"] == PARTS
