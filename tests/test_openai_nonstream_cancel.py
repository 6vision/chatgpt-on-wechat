"""A non-streaming OpenAI-compatible run must be cancellable.

`stream` is the client's choice and defaults to False, so the non-streaming path
is the *default* one. It used to call `run_chat` without registering the run,
and `cancel_session` -- what the console's `/cancel` fast path calls -- reads the
registry's per-session index, which only `register` fills. So `/cancel` answered
"nothing to cancel" while the agent kept working, and the client had no
`request_id` to cancel by either, because this surface only returns one once the
reply is complete.
"""

import threading
import unittest
from unittest.mock import patch

from channel.web.api import openai_compat as oc


class NonStreamingCancellationTest(unittest.TestCase):
    def setUp(self):
        from agent.protocol import get_cancel_registry

        self.registry = get_cancel_registry()
        # The registry is a process-wide singleton; leave nothing behind.
        self.addCleanup(self.registry.unregister, "chatcmpl-test")

    @staticmethod
    def _run_chat_that_blocks(reached, release):
        """A run_chat stand-in that parks, so the test can cancel mid-flight."""

        def run_chat(query, session_id, send_chunk, **kwargs):
            reached.set()
            release.wait(timeout=5)
            send_chunk({"chunk_type": "content", "delta": "done"})

        return run_chat

    def test_the_run_is_registered_while_it_is_in_flight(self):
        reached, release = threading.Event(), threading.Event()
        release.set()  # no need to actually block for the registry check

        with patch.object(oc, "_request_cancel_scope",
                          return_value=("chatcmpl-test", "sess-x")), \
             patch("agent.protocol.get_cancel_registry", return_value=self.registry):
            oc._non_stream_completion(
                self._run_chat_that_blocks(reached, release),
                query="hi", session_id="sess-x",
                completion_id="chatcmpl-test", created=0, model="m",
            )

        # Already unregistered by the finally, so nothing is left dangling --
        # but the entry must have existed while the run was going.
        self.assertNotIn("chatcmpl-test", self.registry._by_request,
                         "the entry was never removed, so it leaked")

    def test_cancel_reaches_a_non_streaming_run(self):
        reached, release = threading.Event(), threading.Event()
        observed = {}

        def run_chat(query, session_id, send_chunk, **kwargs):
            reached.set()
            # What the console's /cancel does while this is running.
            observed["cancelled"] = self.registry.cancel_session("sess-y")
            release.set()
            send_chunk({"chunk_type": "content", "delta": "done"})

        with patch.object(oc, "_request_cancel_scope",
                          return_value=("chatcmpl-cancel", "sess-y")), \
             patch("agent.protocol.get_cancel_registry", return_value=self.registry):
            oc._non_stream_completion(
                run_chat,
                query="hi", session_id="sess-y",
                completion_id="chatcmpl-cancel", created=0, model="m",
            )

        self.assertEqual(
            observed.get("cancelled"), 1,
            "cancel_session found nothing, so /cancel would report that there "
            "was nothing to cancel while the run continued",
        )

    def test_the_entry_is_removed_after_a_successful_run(self):
        with patch.object(oc, "_request_cancel_scope",
                          return_value=("chatcmpl-done", "sess-z")), \
             patch("agent.protocol.get_cancel_registry", return_value=self.registry):
            oc._non_stream_completion(
                lambda q, s, cb, **kw: cb({"chunk_type": "content", "delta": "x"}),
                query="hi", session_id="sess-z",
                completion_id="chatcmpl-done", created=0, model="m",
            )

        self.assertNotIn("chatcmpl-done", self.registry._by_request)
        self.assertEqual(self.registry.cancel_session("sess-z"), 0,
                         "a finished run is still cancellable")

    def test_the_entry_is_removed_after_a_failed_run(self):
        def boom(*args, **kwargs):
            raise RuntimeError("upstream is down")

        with patch.object(oc, "_request_cancel_scope",
                          return_value=("chatcmpl-boom", "sess-w")), \
             patch("agent.protocol.get_cancel_registry", return_value=self.registry):
            with self.assertRaises(oc.OpenAIAPIError):
                oc._non_stream_completion(
                    boom, query="hi", session_id="sess-w",
                    completion_id="chatcmpl-boom", created=0, model="m",
                )

        self.assertNotIn(
            "chatcmpl-boom", self.registry._by_request,
            "a failed run left a cancellable entry behind",
        )


if __name__ == "__main__":
    unittest.main()
