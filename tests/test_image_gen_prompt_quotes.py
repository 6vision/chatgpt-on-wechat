# encoding:utf-8
"""Curly quotes are straightened only when the raw argument JSON fails to parse."""

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_SCRIPT = Path(__file__).parents[1] / "skills" / "image-generation" / "scripts" / "generate.py"
_SPEC = importlib.util.spec_from_file_location("image_gen_quote_script", _SCRIPT)
image_generation = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(image_generation)


def _prompt_sent(raw):
    provider = MagicMock(model="m")
    provider.generate.return_value = ["out.png"]
    with patch.object(image_generation, "_build_providers", return_value=[("p", provider)]), \
            patch.object(sys, "argv", ["generate.py", raw]):
        image_generation.main()
    return provider.generate.call_args.args[0]


@pytest.mark.parametrize("prompt", [
    "a sign reading \u201cHello\u201d in serif",
    "a sign saying don\u2019t stop",
])
def test_valid_payload_keeps_curly_quotes(prompt):
    assert _prompt_sent(json.dumps({"prompt": prompt}, ensure_ascii=False)) == prompt


def test_curly_quote_delimiters_still_recovered():
    assert _prompt_sent("{\u201cprompt\u201d: \u201ca cat\u201d}") == "a cat"
