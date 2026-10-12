# encoding:utf-8
"""
Extra HTTP headers for custom providers, and gateway session headers.

Covers:
  - ``headers`` on a custom_providers entry reaches the OpenAI HTTP client
  - malformed header values are dropped instead of breaking requests
  - gateways that route by session (OpenCode Go) get a stable, hashed
    per-conversation id plus a client user agent; other hosts get nothing
  - user-configured headers win over the built-in ones
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module  # noqa: E402
from config import Config  # noqa: E402
from common.runtime_identity import RuntimeIdentity, use_identity  # noqa: E402
from models.openai.openai_http_client import (  # noqa: E402
    OpenAIHTTPClient,
    resolve_host_headers,
)

OPENCODE_URL = "https://opencode.ai/zen/go/v1/chat/completions"


def set_conf(d):
    config_module.config = Config(d)


class TestProviderHeaders(unittest.TestCase):
    def test_headers_resolved_for_custom_bot_type(self):
        from models.custom_provider import resolve_custom_headers
        set_conf({
            "bot_type": "custom:abc",
            "custom_providers": [
                {"id": "abc", "name": "p", "api_base": "https://x/v1",
                 "headers": {"X-Foo": "bar", "X-Num": 1}},
            ],
        })
        self.assertEqual(resolve_custom_headers(), {"X-Foo": "bar", "X-Num": "1"})

    def test_malformed_values_dropped(self):
        from models.custom_provider import get_provider_headers
        entry = {"headers": {"": "x", "X-None": None, "X-List": [1], "X-Ok": "ok"}}
        self.assertEqual(get_provider_headers(entry), {"X-Ok": "ok"})
        self.assertEqual(get_provider_headers({"headers": "nope"}), {})
        self.assertEqual(get_provider_headers(None), {})

    def test_legacy_and_non_custom_have_no_headers(self):
        from models.custom_provider import resolve_custom_headers
        set_conf({"custom_providers": [{"id": "abc", "headers": {"X-Foo": "bar"}}]})
        self.assertEqual(resolve_custom_headers("custom"), {})
        self.assertEqual(resolve_custom_headers("openai"), {})
        self.assertEqual(resolve_custom_headers("custom:missing"), {})

    def test_chatgpt_bot_client_carries_provider_headers(self):
        from models.chatgpt.chat_gpt_bot import ChatGPTBot
        set_conf({
            "bot_type": "custom:abc",
            "custom_providers": [
                {"id": "abc", "name": "p", "api_key": "k", "api_base": "https://x/v1",
                 "model": "m", "headers": {"X-Foo": "bar"}},
            ],
        })
        bot = ChatGPTBot("custom:abc")
        headers = bot._http_client._build_headers(None, None, url="https://x/v1/chat/completions")
        self.assertEqual(headers["X-Foo"], "bar")
        self.assertEqual(headers["Authorization"], "Bearer k")


class TestGatewaySessionHeaders(unittest.TestCase):
    def test_other_hosts_get_no_session_header(self):
        headers = resolve_host_headers("https://api.example.com/v1/chat/completions")
        self.assertEqual(headers, {})

    def test_opencode_gets_session_and_user_agent(self):
        with use_identity(RuntimeIdentity(session_id="user-123")):
            headers = resolve_host_headers(OPENCODE_URL)
        session = headers["x-opencode-session"]
        self.assertTrue(session)
        self.assertNotIn("user-123", session)
        self.assertTrue(headers["User-Agent"].startswith("CowAgent"))

    def test_session_id_stable_per_conversation(self):
        with use_identity(RuntimeIdentity(session_id="a")):
            first = resolve_host_headers(OPENCODE_URL)["x-opencode-session"]
            second = resolve_host_headers(OPENCODE_URL)["x-opencode-session"]
        with use_identity(RuntimeIdentity(session_id="b")):
            other = resolve_host_headers(OPENCODE_URL)["x-opencode-session"]
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_falls_back_to_process_id_without_session(self):
        first = resolve_host_headers(OPENCODE_URL)["x-opencode-session"]
        second = resolve_host_headers(OPENCODE_URL)["x-opencode-session"]
        self.assertTrue(first)
        self.assertEqual(first, second)

    def test_configured_headers_override_builtin(self):
        client = OpenAIHTTPClient(api_key="k", extra_headers={"x-opencode-session": "mine"})
        headers = client._build_headers(None, None, url=OPENCODE_URL)
        self.assertEqual(headers["x-opencode-session"], "mine")


if __name__ == "__main__":
    unittest.main()
