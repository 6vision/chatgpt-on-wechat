"""A non-streaming OpenAI-compatible run is registered so /cancel can reach it."""

import unittest
from unittest.mock import patch

from channel.web.api import openai_compat as oc


def _values(session_id):
    return {
        "model": "m", "query": "hi", "session_id": session_id,
        "transcript": None, "stream": False, "include_usage": False,
    }


class NonStreamingCancellationTest(unittest.TestCase):
    def setUp(self):
        from agent.protocol import get_cancel_registry

        self.registry = get_cancel_registry()

    def test_cancel_reaches_a_non_streaming_run(self):
        observed = {}

        def run_chat(query, session_id, send_chunk, **kwargs):
            observed["cancelled"] = self.registry.cancel_session("sess-y")
            send_chunk({"chunk_type": "content", "delta": "done"})

        with patch.object(oc, "_request_cancel_scope",
                          return_value=("chatcmpl-cancel", "sess-y")), \
             patch("agent.protocol.get_cancel_registry", return_value=self.registry):
            oc._non_stream_completion(
                run_chat,
                _values("sess-y"), None,
                completion_id="chatcmpl-cancel", created=0,
            )

        self.assertEqual(observed.get("cancelled"), 1)

    def test_the_entry_is_removed_after_a_successful_run(self):
        with patch.object(oc, "_request_cancel_scope",
                          return_value=("chatcmpl-done", "sess-z")), \
             patch("agent.protocol.get_cancel_registry", return_value=self.registry):
            oc._non_stream_completion(
                lambda q, s, cb, **kw: cb({"chunk_type": "content", "delta": "x"}),
                _values("sess-z"), None,
                completion_id="chatcmpl-done", created=0,
            )

        self.assertNotIn("chatcmpl-done", self.registry._by_request)
        self.assertEqual(self.registry.cancel_session("sess-z"), 0)

    def test_the_entry_is_removed_after_a_failed_run(self):
        def boom(*args, **kwargs):
            raise RuntimeError("upstream is down")

        with patch.object(oc, "_request_cancel_scope",
                          return_value=("chatcmpl-boom", "sess-w")), \
             patch("agent.protocol.get_cancel_registry", return_value=self.registry):
            with self.assertRaises(oc.OpenAIAPIError):
                oc._non_stream_completion(
                    boom, _values("sess-w"), None,
                    completion_id="chatcmpl-boom", created=0,
                )

        self.assertNotIn("chatcmpl-boom", self.registry._by_request)


if __name__ == "__main__":
    unittest.main()
