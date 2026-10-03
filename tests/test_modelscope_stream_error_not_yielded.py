# encoding:utf-8

"""A mid-stream ModelScope failure was swallowed: the consumer saw no error.

``ModelScopeBot._handle_stream_response`` is a generator function, and its
``except`` handler ended with::

    def error_generator():
        yield {"error": True, "message": error_msg, "status_code": 500}
    return error_generator()

``return <generator>`` inside a generator does not yield anything: it raises
``StopIteration`` carrying the object, which discards it. Every other ``yield``
in the method (a non-200 status at line 548, an error chunk inside the stream at
line 567) hands the consumer an ``{"error": True, ...}`` dict, but this one
produced *nothing* -- so a connection that died after the first tokens arrived
ended the stream as if the model had simply stopped talking. The caller sees a
truncated answer and no indication that the API had failed, which is
indistinguishable from a model that finished early.

The fix yields the error chunk instead of returning it, matching
``claude_api_bot.py:741`` -- the in-generator spelling this repo already uses.
The test below drives a real mid-stream failure and asserts the consumer
actually receives an error chunk.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.modelscope.modelscope_bot import ModelScopeBot


class _FakeSession:
    """Just enough session for the converter to read its messages."""

    def __init__(self):
        self.messages = [{"role": "user", "content": "hi"}]


class _DyingStreamResponse:
    """A 200 SSE response that raises part-way through the stream."""

    status_code = 200

    def __init__(self, before_failure=b'data: {"choices": [{"delta": {"content": "partial"}}]}'):
        self._before_failure = before_failure
        self.text = ""

    def iter_lines(self):
        yield self._before_failure
        raise OSError("connection reset by peer mid-stream")


def _drive_stream(response, model="Qwen/Qwen3-8B"):
    """Run the real stream handler against a stubbed transport.

    ``_handle_stream_response`` needs nothing from ``self`` beyond an api_key,
    base_url and a session, so the instance is built with ``__new__`` and the
    network is replaced rather than opened.
    """
    import models.modelscope.modelscope_bot as mb

    bot = ModelScopeBot.__new__(ModelScopeBot)
    bot.sessions = _FakeSession()
    bot.api_key = "test-key"
    bot.base_url = "http://localhost"

    original_post = mb.requests.post
    mb.requests.post = lambda *a, **k: response
    try:
        return list(bot._handle_stream_response(bot.sessions, {"model": model}))
    finally:
        mb.requests.post = original_post


class TestMidStreamFailureYieldsAnErrorChunk(unittest.TestCase):
    """The failure must reach the consumer instead of ending the stream."""

    def test_mid_stream_failure_delivers_an_error_chunk(self):
        """The reported defect: the consumer iterated and saw no error."""
        chunks = _drive_stream(_DyingStreamResponse())

        errors = [c for c in chunks if isinstance(c, dict) and c.get("error")]
        self.assertEqual(
            len(errors),
            1,
            "the mid-stream failure produced no error chunk; the consumer "
            "cannot tell a truncated stream from a model that stopped early",
        )
        self.assertEqual(errors[0]["status_code"], 500)
        self.assertIn("connection reset by peer", str(errors[0]["message"]))

    def test_the_error_chunk_carries_a_usable_message(self):
        """An error chunk with an empty message tells the user nothing."""
        chunks = _drive_stream(_DyingStreamResponse())

        errors = [c for c in chunks if isinstance(c, dict) and c.get("error")]
        self.assertTrue(errors, "no error chunk was delivered")
        self.assertTrue(str(errors[0].get("message", "")).strip())

    def test_text_yielded_before_the_failure_is_still_delivered(self):
        """The fix must not swallow the tokens that already arrived.

        The stream is additive: the partial answer plus one error chunk is the
        honest account of what happened, and discarding the partial text would
        trade one wrong behaviour for another.
        """
        chunks = _drive_stream(_DyingStreamResponse())

        text = "".join(
            str(delta.get("content", ""))
            for c in chunks
            for choice in (c.get("choices") or [])
            for delta in [choice.get("delta") or {}]
        )
        self.assertIn("partial", text)

    def test_a_clean_stream_has_no_error_chunk(self):
        """The happy path must not start inventing errors."""
        done = b"data: [DONE]"
        good = b'data: {"choices": [{"delta": {"content": "all good"}}]}'

        class _CleanResponse:
            status_code = 200
            text = ""

            def iter_lines(self):
                yield good
                yield done

        chunks = _drive_stream(_CleanResponse())

        self.assertFalse([c for c in chunks if c.get("error")])
        self.assertEqual(len(chunks), 2)  # the content chunk plus the final chunk


if __name__ == "__main__":
    unittest.main()
