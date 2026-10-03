# encoding:utf-8
"""
Unit tests for the OpenAI-compatible request payload.

The agent carries private bookkeeping keys on the messages it keeps between
turns. ``_gemini_raw_parts`` is the clearest one: the Gemini stream handler
attaches the provider's original parts to the assistant message so the
thoughtSignature can be handed back on the next turn.

``_convert_messages_to_openai_format`` copies that marker onto the
OpenAI-shaped message, because the LinkAI proxy genuinely needs it echoed
back. But the marker is not part of any API schema: it is a Python-side
convention, and the request that finally goes out carries it verbatim. The
payload filter on the way out only drops ``None`` values, so nothing else
removes it. A strict OpenAI-compatible endpoint answers the whole request with
HTTP 400 "Unrecognized request argument supplied" -- the model switch that put
a Gemini turn into the history permanently breaks every later request on that
endpoint, with a message that names neither the model nor the conversation.

These cover the request body actually being serialized: no key that is not
part of the API schema may appear in it.
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _assistant_with_marker(marker=None):
    """A Claude-format assistant turn as the agent history stores it."""
    message = {
        "role": "assistant",
        "content": [{"type": "text", "text": "here is the answer"}],
    }
    if marker is not None:
        message["_gemini_raw_parts"] = marker
    return message


class TestOpenAICompatibleWirePayload(unittest.TestCase):
    """Nothing private may survive into the serialized request body."""

    def _wire_payload(self, messages):
        from models.openai import openai_http_client
        from models.openai_compatible_bot import OpenAICompatibleBot

        class _Bot(OpenAICompatibleBot):
            def get_api_config(self):
                return {
                    "model": "gpt-4o",
                    "api_key": "test-key",
                    "api_base": "https://example.invalid/v1",
                }

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "model": "gpt-4o",
            "choices": [{"message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        with patch.object(openai_http_client.requests, "post", return_value=response) as post:
            _Bot().call_with_tools(messages, tools=None, stream=False)

        self.assertTrue(post.call_count, "no request was sent")
        body = post.call_args.kwargs["json"]
        # Assert on the bytes that leave the process, not on the dict we built.
        return json.loads(json.dumps(body))

    def test_converted_assistant_message_still_carries_the_marker(self):
        # The conversion itself is unchanged: LinkAI depends on the marker
        # being echoed, so it must survive into the converted messages.
        from models.openai_compatible_bot import OpenAICompatibleBot

        converted = OpenAICompatibleBot()._convert_messages_to_openai_format(
            [_assistant_with_marker(marker=[{"text": "hi", "thoughtSignature": "sig"}])]
        )
        self.assertEqual(
            converted[0]["_gemini_raw_parts"],
            [{"text": "hi", "thoughtSignature": "sig"}],
        )

    def test_marker_is_absent_from_the_serialized_request_body(self):
        payload = self._wire_payload(
            [_assistant_with_marker(marker=[{"text": "hi", "thoughtSignature": "sig"}])]
        )
        assistant = [m for m in payload["messages"] if m["role"] == "assistant"]
        self.assertTrue(assistant)
        for key in assistant[0]:
            self.assertFalse(
                key.startswith("_"),
                f"private key {key!r} was sent to the endpoint",
            )

    def test_no_message_carries_any_private_key(self):
        # Whichever turn the marker is attached to, it must not be on the wire.
        payload = self._wire_payload([
            {"role": "user", "content": "first question"},
            _assistant_with_marker(marker=[{"text": "hi", "thoughtSignature": "sig"}]),
            {"role": "user", "content": "second question"},
        ])
        for message in payload["messages"]:
            for key in message:
                self.assertFalse(
                    key.startswith("_"),
                    f"private key {key!r} was sent to the endpoint",
                )

    def test_ordinary_history_produces_an_unchanged_body(self):
        # The plain path must be untouched: same keys, same order.
        payload = self._wire_payload([
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "an answer"},
            {"role": "user", "content": "second question"},
        ])
        self.assertEqual(
            [m["role"] for m in payload["messages"]],
            ["user", "assistant", "user"],
        )
        self.assertEqual(payload["messages"][1]["content"], "an answer")


if __name__ == "__main__":
    unittest.main()
