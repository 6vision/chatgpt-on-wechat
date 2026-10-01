"""``env_config`` must not write an entry that reads back as two.

``~/.cow/.env`` is line-oriented, and that assumption is made independently in
three places: this tool's own ``_read_env_file``, and python-dotenv through
``bridge/agent_initializer.py`` (``load_dotenv``) and ``agent/tools/bash/bash.py``
(``dotenv_values``, whose values are also what ``_redact_progress`` scrubs out of
tool output). ``_write_env_file`` emits plain ``KEY=VALUE`` lines with no quoting
and no check, so a value containing a line break does not fail - it silently
becomes a shorter value plus one or more extra entries.

The consequences are not cosmetic. The stored API key is no longer the key that
was set, so the provider that needed it keeps failing while ``list`` reports the
key as configured. And every line after the break is parsed as its own
assignment, which turns the tail of a value into an environment variable that
then reaches ``os.environ`` through ``_reload_env`` and every bash subprocess
through ``dotenv_values``.
"""

import pytest

from agent.tools.env_config.env_config import EnvConfig


@pytest.fixture()
def tool(tmp_path):
    """An EnvConfig pinned to a temp dir; the developer's ~/.cow is never used."""
    instance = EnvConfig(config={})
    instance.env_dir = str(tmp_path)
    instance.env_path = str(tmp_path / ".env")
    instance._ensure_env_file()
    return instance


def _text(tool):
    with open(tool.env_path, encoding="utf-8") as handle:
        return handle.read()


def _set(tool, key, value):
    return tool.execute({"action": "set", "key": key, "value": value})


# ---------------------------------------------------------------------------
# The defect: a value that spans lines is stored as several entries.
# ---------------------------------------------------------------------------

def test_a_multiline_value_is_refused_rather_than_split(tool):
    failed = _set(tool, "OPENAI_API_KEY", "sk-live-secret\nPROVIDER=evil")

    assert failed.status == "error"
    assert _text(tool) == ""
    assert tool._read_env_file() == {}


def test_the_split_never_reaches_the_readers(tool):
    """The invariant, asserted on the state both readers see.

    Before the fix this call reports success and leaves the file holding two
    variables: the key cut off at the line break, and one the caller never set -
    which ``_reload_env`` then pushes into ``os.environ``, and ``bash`` into every
    subprocess through ``dotenv_values``.
    """
    from dotenv import dotenv_values

    _set(tool, "OPENAI_API_KEY", "sk-live-secret\nPROVIDER=evil")

    assert "PROVIDER" not in tool._read_env_file()
    assert "PROVIDER" not in dict(dotenv_values(tool.env_path))
    assert tool._read_env_file() == dict(dotenv_values(tool.env_path))


def test_a_refused_value_does_not_disturb_the_keys_already_stored(tool):
    assert _set(tool, "LINKAI_API_KEY", "linkai-live-key").status == "success"

    assert _set(tool, "OPENAI_API_KEY", "one\ntwo").status == "error"

    assert tool._read_env_file() == {"LINKAI_API_KEY": "linkai-live-key"}
    listed = tool.execute({"action": "list"})
    assert list(listed.result["variables"]) == ["LINKAI_API_KEY"]


def test_a_key_that_is_not_one_field_is_refused(tool):
    """A key carrying the separator aliases onto a different name."""
    assert _set(tool, "A=INJECTED", "1").status == "error"

    assert tool._read_env_file() == {}


# ---------------------------------------------------------------------------
# The guard must stay narrow: single-line values keep working as before.
# ---------------------------------------------------------------------------

def test_ordinary_values_still_round_trip(tool):
    cases = {
        "OPENAI_API_KEY": "sk-or-v1-abc123",
        # '=' and '#' inside the value are the shapes the parser already handles,
        # and a base64 blob padded with '=' is the common real case.
        "GOOGLE_SERVICE_ACCOUNT": "eyJhbGciOi===" * 3,
        "SEARCH_PROVIDER": "bocha",
        "WITH_HASH": "abc#def",
        "WITH_TRAILING_SPACE": "padded ",
    }
    for key, value in cases.items():
        assert _set(tool, key, value).status == "success", key

    stored = tool._read_env_file()
    assert {k: v for k, v in stored.items() if k in cases} == {
        k: v.rstrip() for k, v in cases.items()
    }
