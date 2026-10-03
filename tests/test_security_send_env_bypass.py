# encoding:utf-8
"""The Send tool refuses credential paths (even missing ones) before checking existence."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.send.send import Send


@pytest.fixture
def home(tmp_path, monkeypatch):
    # ntpath.expanduser reads USERPROFILE, not HOME.
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path))
    (tmp_path / ".cow").mkdir()
    (tmp_path / "cow").mkdir()
    return tmp_path


@pytest.mark.parametrize("exists", [True, False])
def test_credential_path_is_denied(home, exists):
    if exists:
        (home / ".cow" / ".env").write_text("OPENAI_API_KEY=sk-SECRET\n")
    result = Send({"cwd": str(home / "cow")}).execute({"path": "~/.cow/.env"})
    assert result.status == "error"
    assert "Access denied" in str(result.result)


def test_ordinary_file_is_sent(home):
    (home / "cow" / "note.txt").write_text("hello")
    result = Send({"cwd": str(home / "cow")}).execute({"path": "note.txt"})
    assert result.status == "success"
    assert result.result["type"] == "file_to_send"
