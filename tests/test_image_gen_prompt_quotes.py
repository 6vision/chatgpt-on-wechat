# encoding:utf-8
"""
Regression tests for typographic quotes in the image-generation argument JSON.

``generate.main`` rewrote U+201C/U+201D/U+2018/U+2019 to straight quotes across
the whole raw argument string *before* handing it to ``json.loads``. Straight
double quotes are the JSON string delimiter, so a perfectly valid payload whose
prompt merely contained a typographic quote -- a sign reading "Hello", a book
title -- was rewritten into malformed JSON and the entire call died with
"Invalid JSON" instead of generating anything. A prompt with a typographic
apostrophe ("don't") survived but reached the image API with the apostrophe
flattened to a straight one.

Normalizing before parsing is also what rescues an agent that emitted curly
quotes as the JSON delimiters themselves, so the replacement cannot simply be
dropped: that recovery has to stay. These tests pin both halves -- parse the
payload untouched first, and only fall back to normalizing when it does not
parse.
"""

import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "skills"
    / "image-generation"
    / "scripts"
    / "generate.py"
)
_SPEC = importlib.util.spec_from_file_location("image_gen_quote_script", _SCRIPT_PATH)
image_generation = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(image_generation)

LQ, RQ = "\u201c", "\u201d"
LSQ, RSQ = "\u2018", "\u2019"


class _RecordingProvider:
    """Stands in for a real provider and remembers how it was called."""

    model = "recording-model"

    def __init__(self):
        self.prompts = []
        self.calls = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        self.calls.append(kwargs)
        return [os.path.join("images", "out.png")]


def _run_main(raw_argv):
    """Drive main() with one argument string; return (provider, stdout).

    ``_build_providers`` is stubbed out so nothing reaches the network and the
    prompt main() parsed can be inspected directly.
    """
    provider = _RecordingProvider()
    out = io.StringIO()
    argv = ["generate.py", raw_argv]
    with patch.object(image_generation, "_build_providers",
                      return_value=[("recording", provider)]), \
            patch.object(sys, "argv", argv), \
            redirect_stdout(out):
        image_generation.main()
    return provider, out.getvalue()


def _parse_error(raw_argv):
    """Return the JSON error main() printed, or None when it did not exit."""
    out = io.StringIO()
    argv = ["generate.py", raw_argv]
    with patch.object(image_generation, "_build_providers",
                      return_value=[("recording", _RecordingProvider())]), \
            patch.object(sys, "argv", argv), \
            redirect_stdout(out):
        try:
            image_generation.main()
        except SystemExit:
            pass
    try:
        payload = json.loads(out.getvalue())
    except ValueError:
        return None
    return payload.get("error")


class TestPromptKeepsTypographicQuotes(unittest.TestCase):
    """Curly quotes inside a valid payload must reach the provider verbatim."""

    def test_double_quotes_in_prompt_are_not_flattened(self):
        """U+201C/U+201D inside the prompt survive to the image API.

        These are ordinary characters inside a JSON string, so the payload is
        valid as written; rewriting them to " ends the string early and the
        call fails outright.
        """
        prompt = f"a sign reading {LQ}Hello{RQ} in serif"
        raw = json.dumps({"prompt": prompt}, ensure_ascii=False)

        provider, _ = _run_main(raw)

        self.assertEqual(provider.prompts, [prompt])

    def test_double_quotes_in_prompt_do_not_fail_the_call(self):
        """The user-visible consequence: the request used to abort entirely."""
        prompt = f"a sign reading {LQ}Hello{RQ} in serif"
        raw = json.dumps({"prompt": prompt}, ensure_ascii=False)

        self.assertIsNone(_parse_error(raw))

    def test_apostrophe_inside_a_word_is_not_flattened(self):
        """A typographic apostrophe in "don't" reaches the provider as U+2019."""
        prompt = f"a sign saying don{RSQ}t stop"
        raw = json.dumps({"prompt": prompt}, ensure_ascii=False)

        provider, _ = _run_main(raw)

        self.assertEqual(provider.prompts, [prompt])

    def test_single_quotes_in_prompt_survive(self):
        """U+2018/U+2019 are not JSON delimiters, but were still rewritten."""
        prompt = f"the word {LSQ}yes{RSQ} on a sign"
        raw = json.dumps({"prompt": prompt}, ensure_ascii=False)

        provider, _ = _run_main(raw)

        self.assertEqual(provider.prompts, [prompt])

    def test_non_prompt_fields_keep_their_typographic_quotes(self):
        """The rewrite hit every field, not just the prompt."""
        raw = json.dumps(
            {"prompt": "x", "size": f"1024x1024{RSQ}"},
            ensure_ascii=False,
        )

        provider, _ = _run_main(raw)

        self.assertEqual(provider.prompts, ["x"])
        self.assertEqual(provider.calls[0]["size"], f"1024x1024{RSQ}")

    def test_plain_prompt_is_unchanged(self):
        """A payload with no typographic quotes behaves exactly as before."""
        raw = json.dumps({"prompt": "a cat", "size": "1024x1024"})

        provider, _ = _run_main(raw)

        self.assertEqual(provider.prompts, ["a cat"])

    def test_escaped_typographic_quotes_in_json_also_survive(self):
        """The \\uXXXX escape form reaches json.loads identically."""
        raw = '{"prompt": "a sign reading \\u201cHello\\u201d in serif"}'

        provider, _ = _run_main(raw)

        self.assertEqual(provider.prompts, [f"a sign reading {LQ}Hello{RQ} in serif"])


class TestMalformedJsonRecoveryIsKept(unittest.TestCase):
    """Curly quotes used as the delimiters are still recovered, not dropped."""

    def test_curly_quotes_as_delimiters_are_still_accepted(self):
        """An agent emitting {"prompt": "..."} must keep working.

        This is what the unconditional rewrite was actually for; dropping it
        outright would turn a recoverable call into "Invalid JSON".
        """
        raw = "{" + LQ + "prompt" + RQ + ": " + LQ + "a cat" + RQ + "}"

        provider, _ = _run_main(raw)

        self.assertEqual(provider.prompts, ["a cat"])

    def test_curly_quotes_as_delimiters_with_extra_fields(self):
        """Recovery still works when other fields are present alongside."""
        raw = (
            "{" + LQ + "prompt" + RQ + ": " + LQ + "a cat" + RQ
            + ", " + LQ + "size" + RQ + ": " + LQ + "1024x1024" + RQ + "}"
        )

        provider, _ = _run_main(raw)

        self.assertEqual(provider.prompts, ["a cat"])

    def test_genuinely_broken_json_is_still_rejected(self):
        """Unfixable input keeps reporting Invalid JSON and exiting non-zero."""
        self.assertIn("Invalid JSON", _parse_error('{"prompt": '))

    def test_missing_prompt_is_still_rejected(self):
        """The prompt check is untouched by the parse change."""
        self.assertIn("Missing required parameter", _parse_error(json.dumps({"size": "1024x1024"})))

    def test_non_object_arguments_are_still_rejected(self):
        """A JSON array is a parse success but not a valid argument object."""
        self.assertIn("must be a JSON object", _parse_error("[1, 2]"))


if __name__ == "__main__":
    unittest.main()
