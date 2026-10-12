# encoding:utf-8
"""``generate.py`` must answer every bad call with its JSON error envelope.

The script is invoked by the skill with a JSON argument, and every failure it
handles prints ``{"error": ...}`` so the caller has something to read. Only
``json.JSONDecodeError`` was handled, though, so valid JSON that was not an
object -- a bare list, string, number, ``true`` or ``null`` -- reached
``args.get("prompt")`` and died with an ``AttributeError`` traceback on stderr
and nothing at all on stdout.

All the cases below exit before the script does any network work.
"""

import json
import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills", "image-generation", "scripts", "generate.py",
)


def run(payload):
    proc = subprocess.run(
        [sys.executable, SCRIPT, payload],
        capture_output=True, text=True, timeout=120,
    )
    return proc


def envelope_of(proc):
    """Parse the JSON error envelope, asserting nothing leaked to stderr."""
    assert "Traceback (most recent call last)" not in proc.stderr, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize("payload", ["[1, 2]", "null", "42", "true", '"hi"'])
def test_valid_json_that_is_not_an_object_is_reported_as_such(payload):
    proc = run(payload)

    assert proc.returncode == 1
    assert envelope_of(proc) == {"error": "Arguments must be a JSON object"}


def test_malformed_json_still_reports_invalid_json():
    proc = run("{not json}")

    assert proc.returncode == 1
    assert envelope_of(proc)["error"].startswith("Invalid JSON")


def test_an_object_without_a_prompt_is_still_reported():
    proc = run('{"model": "m"}')

    assert proc.returncode == 1
    assert envelope_of(proc) == {"error": "Missing required parameter: prompt"}


def test_an_empty_object_is_still_reported():
    proc = run("{}")

    assert proc.returncode == 1
    assert envelope_of(proc) == {"error": "Missing required parameter: prompt"}


def test_no_argument_still_reports_usage():
    proc = subprocess.run(
        [sys.executable, SCRIPT], capture_output=True, text=True, timeout=120
    )

    assert proc.returncode == 1
    assert "Usage" in envelope_of(proc)["error"]
