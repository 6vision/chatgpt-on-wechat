# encoding:utf-8
"""A MiniMax stream error chunk whose ``http_code`` arrives as a number.

``MinimaxBot._handle_stream_response`` reads the status off the provider's own
SSE error chunk and converted it with::

    "status_code": int(http_code) if http_code.isdigit() else 500

``http_code`` is whatever the provider put in the payload, and nothing in the
wire format pins it to a string. MiniMax documents the field as a string and
mostly sends one, but JSON has no such distinction -- ``{"http_code": 429}`` and
``{"http_code": "429"}`` are equally valid encodings of the same fact, and a
proxy that re-serialises the chunk, or a provider revision that fixes the
typing, sends the numeric form. ``int.isdigit()`` is then an ``AttributeError``.

The damage is that it happens on the line whose entire job is to report the
failure faithfully. The exception unwinds to the ``except Exception`` at the
bottom of the method, which yields ``{"error": True, "message": str(e), ...}``
-- so the message the user is shown becomes ``"'int' object has no attribute
'isdigit'"``, which describes the bot's own bug and tells the caller nothing,
and the status the caller is given is a generic 500 rather than the 429 the
provider actually reported. A caller deciding whether to back off and retry sees
a server fault instead of a rate limit and retries into the limit.

The fix is the coercion ``models/linkai/link_ai_bot.py`` already applies to the
same field in the same OpenAI-compatible error shape: test ``str(http_code)``
rather than ``http_code``, so both encodings are accepted and the fallback is
reached only when the value really is not a number.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _bot():
    """A MinimaxBot holding only the state ``_handle_stream_response`` reads.

    ``__init__`` builds a SessionManager out of the developer's config, which a
    test should not touch, so this goes through ``__new__`` the way the existing
    minimax tests do.
    """
    from models.minimax.minimax_bot import MinimaxBot

    return MinimaxBot.__new__(MinimaxBot)


class _StreamResponse:
    """A 200 response whose body is a canned SSE stream."""

    def __init__(self, *chunks):
        self.status_code = 200
        lines = [f"data: {json.dumps(chunk)}" for chunk in chunks]
        lines.append("data: [DONE]")
        self.iter_lines = MagicMock(
            return_value=[line.encode("utf-8") for line in lines]
        )


def _stream_chunks(*stream_chunks):
    """Run the stream handler over an SSE body and return what it yields.

    The handler is a generator, and what matters here is what it yields -- the
    error branch's whole purpose is the dict it hands back -- so the chunks are
    collected rather than the call being read for a single value.
    """
    conf = {"minimax_api_key": "test-key", "minimax_api_base": "https://api.minimaxi.com/v1"}
    with patch("models.minimax.minimax_bot.conf", return_value=conf):
        with patch("models.minimax.minimax_bot.requests.post",
                   return_value=_StreamResponse(*stream_chunks)):
            return list(_bot()._handle_stream_response({"model": "MiniMax-M3"}))


def _error_chunk(error):
    return {"type": "error", "error": error}


class TestMinimaxStreamErrorHttpCodeType(unittest.TestCase):
    """The status reported to the caller must be the one the provider reported."""

    def test_a_numeric_http_code_is_reported_as_its_own_status(self):
        """``{"http_code": 429}`` is the same fact as ``{"http_code": "429"}``.

        JSON does not distinguish the two encodings, so the reader of the field
        has to accept both. Before this, the number raised ``AttributeError`` on
        ``.isdigit()`` and the caller was handed a 500.
        """
        chunks = _stream_chunks(_error_chunk({
            "message": "rate limited", "type": "rate_limit_error", "http_code": 429,
        }))

        self.assertEqual(chunks, [
            {"error": True, "message": "rate limited", "status_code": 429}
        ])

    def test_a_numeric_http_code_does_not_leak_the_bug_into_the_message(self):
        """The message the user sees must be the provider's, not ``str(e)``.

        This is the half of the defect that reaches the chat window: the
        blanket handler replaces the message with the text of the
        ``AttributeError`` it raised while formatting that very message.
        """
        chunks = _stream_chunks(_error_chunk({
            "message": "insufficient balance", "type": "billing_error",
            "http_code": 402,
        }))

        self.assertEqual(chunks[0]["message"], "insufficient balance")
        self.assertNotIn("isdigit", chunks[0]["message"])

    def test_a_string_http_code_still_reports_its_own_status(self):
        """The documented string form is unchanged -- this is not a replacement."""
        chunks = _stream_chunks(_error_chunk({
            "message": "bad request", "type": "invalid_request", "http_code": "400",
        }))

        self.assertEqual(chunks, [
            {"error": True, "message": "bad request", "status_code": 400}
        ])

    def test_a_null_http_code_falls_back_rather_than_raising(self):
        """``None`` reaches ``.isdigit()`` as an ``AttributeError`` as well.

        A chunk that omits the field's value is no rarer than one that spells it
        numerically, and it took the same path down.
        """
        chunks = _stream_chunks(_error_chunk({
            "message": "upstream failure", "type": "server_error", "http_code": None,
        }))

        self.assertEqual(chunks, [
            {"error": True, "message": "upstream failure", "status_code": 500}
        ])

    def test_a_missing_http_code_falls_back_to_the_server_error(self):
        """No field at all still means the generic 500, as it did before."""
        chunks = _stream_chunks(_error_chunk({
            "message": "something went wrong", "type": "unknown",
        }))

        self.assertEqual(chunks, [
            {"error": True, "message": "something went wrong", "status_code": 500}
        ])

    def test_a_non_numeric_http_code_still_falls_back(self):
        """A value that is not a number at all still means 500.

        Coercing to ``str`` must not start reporting nonsense as a status.
        """
        for value in ("not-a-number", "", [429], {"code": 429}):
            with self.subTest(http_code=value):
                chunks = _stream_chunks(_error_chunk({
                    "message": "weird status", "type": "unknown", "http_code": value,
                }))

                self.assertEqual(chunks, [
                    {"error": True, "message": "weird status", "status_code": 500}
                ])

    def test_the_stream_stops_at_the_error_chunk(self):
        """Reporting the right status must not change when the stream ends.

        An error chunk is terminal, so nothing after it should be yielded --
        content the provider sent after reporting an error is not part of the
        answer.
        """
        chunks = _stream_chunks(
            _error_chunk({"message": "rate limited", "http_code": 429}),
            {"choices": [{"delta": {"content": "should not appear"}, "index": 0}]},
        )

        self.assertEqual(chunks, [
            {"error": True, "message": "rate limited", "status_code": 429}
        ])

    def test_a_chunk_with_an_error_key_and_no_type_is_still_handled(self):
        """The branch triggers on either condition, so both shapes reach it."""
        chunks = _stream_chunks({
            "error": {"message": "quota exhausted", "http_code": 429},
        })

        self.assertEqual(chunks, [
            {"error": True, "message": "quota exhausted", "status_code": 429}
        ])

    def test_a_normal_stream_is_unaffected(self):
        """Only the error branch was touched; content still comes through.

        The stream handler yields OpenAI-format deltas rather than content
        blocks, so this pins the shape a normal turn actually produces -- the
        point being that none of it turns into an error chunk.
        """
        chunks = _stream_chunks({
            "choices": [{"delta": {"content": "hello"}, "index": 0}],
        })

        deltas = [c["choices"][0]["delta"] for c in chunks if "choices" in c]
        self.assertEqual("".join(d.get("content") or "" for d in deltas), "hello")
        self.assertFalse([c for c in chunks if c.get("error")])


if __name__ == "__main__":
    unittest.main()
