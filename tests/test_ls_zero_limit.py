"""ls must never report a nonempty directory as empty, whatever limit the model passes."""

import pytest

from agent.tools.ls.ls import Ls


@pytest.mark.parametrize("limit", [0, -1, None, "abc", True])
def test_invalid_limits_fall_back_to_the_default(tmp_path, limit):
    (tmp_path / "real-entry.txt").touch()
    result = Ls({"cwd": str(tmp_path)}).execute({"limit": limit})
    assert result.status == "success"
    assert result.result["output"] == "real-entry.txt"


@pytest.mark.parametrize("limit", ["2", 2.9])
def test_numeric_strings_and_floats_are_truncated_to_an_int(tmp_path, limit):
    for name in ["a.txt", "b.txt", "c.txt"]:
        (tmp_path / name).touch()
    result = Ls({"cwd": str(tmp_path)}).execute({"limit": limit})
    assert result.result["entry_count"] == 2
    assert "2 entries limit reached. Use limit=4" in result.result["output"]


def test_an_empty_directory_keeps_the_empty_message(tmp_path):
    result = Ls({"cwd": str(tmp_path)}).execute({"limit": 0})
    assert result.result == {"message": "(empty directory)", "entries": []}


def test_positive_limit_still_lists_and_truncates(tmp_path):
    for name in ["c.txt", "a.txt", "b.txt"]:
        (tmp_path / name).touch()
    result = Ls({"cwd": str(tmp_path)}).execute({"limit": 2})
    assert result.result["entry_count"] == 2
    assert result.result["details"]["entry_limit_reached"] == 2
    assert result.result["output"].startswith("a.txt\nb.txt\n")


def test_exact_positive_limit_does_not_claim_truncation(tmp_path):
    for name in ["a.txt", "b.txt"]:
        (tmp_path / name).touch()
    result = Ls({"cwd": str(tmp_path)}).execute({"limit": 2})
    assert result.result["details"] is None
    assert result.result["output"] == "a.txt\nb.txt"
