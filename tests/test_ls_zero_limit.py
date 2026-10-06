"""A zero-entry request must not imply that a nonempty directory is empty."""

from agent.tools.ls.ls import Ls


def test_zero_limit_on_nonempty_directory_reports_truncation(tmp_path):
    (tmp_path / "real-entry.txt").touch()
    result = Ls({"cwd": str(tmp_path)}).execute({"limit": 0})
    assert result.status == "success"
    assert result.result["entry_count"] == 0
    assert result.result["details"]["entry_limit_reached"] == 0
    assert "empty directory" not in result.result["output"]
    assert "0 entries limit reached" in result.result["output"]
    assert "limit=1" in result.result["output"]


def test_zero_limit_on_empty_directory_keeps_empty_message(tmp_path):
    result = Ls({"cwd": str(tmp_path)}).execute({"limit": 0})
    assert result.status == "success"
    assert result.result == {"message": "(empty directory)", "entries": []}


def test_positive_limit_still_lists_and_truncates(tmp_path):
    for name in ["c.txt", "a.txt", "b.txt"]:
        (tmp_path / name).touch()
    result = Ls({"cwd": str(tmp_path)}).execute({"limit": 2})
    assert result.status == "success"
    assert result.result["entry_count"] == 2
    assert result.result["details"]["entry_limit_reached"] == 2
    assert result.result["output"].startswith("a.txt\nb.txt\n")
    assert "limit=4" in result.result["output"]


def test_exact_positive_limit_does_not_claim_truncation(tmp_path):
    for name in ["a.txt", "b.txt"]:
        (tmp_path / name).touch()
    result = Ls({"cwd": str(tmp_path)}).execute({"limit": 2})
    assert result.status == "success"
    assert result.result["entry_count"] == 2
    assert result.result["details"] is None
    assert result.result["output"] == "a.txt\nb.txt"
