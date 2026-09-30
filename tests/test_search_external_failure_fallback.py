"""A real external regex failure must reach the existing Python fallback."""

import shutil

import pytest

from agent.tools.search_files.search_files import SearchFiles


@pytest.mark.skipif(shutil.which("rg") is None, reason="requires the real ripgrep executable")
@pytest.mark.parametrize("pattern", [r"(?<=id=)\d+", r"id=\d+(?=;)"])
def test_ripgrep_rejected_regex_falls_back_to_real_python_search(tmp_path, pattern):
    (tmp_path / "record.txt").write_text("id=42;\nname=demo\n", encoding="utf-8")
    tool = SearchFiles({"cwd": str(tmp_path)})
    # Select an installed backend exactly as the existing parity fixtures do;
    # its actual subprocess, exit code, and fallback implementation stay real.
    tool._pick_backend = lambda: tool._backend_rg

    result = tool.execute({"pattern": pattern, "path": "."})

    assert result.status == "success", result.result
    assert result.result["matches"] == [{"file": "record.txt", "line": 1, "match": "id=42;"}]


@pytest.mark.skipif(shutil.which("rg") is None, reason="requires the real ripgrep executable")
def test_ripgrep_no_matches_remains_an_ordinary_empty_result(tmp_path):
    (tmp_path / "record.txt").write_text("id=42;\n", encoding="utf-8")
    tool = SearchFiles({"cwd": str(tmp_path)})
    tool._pick_backend = lambda: tool._backend_rg

    result = tool.execute({"pattern": "missing", "path": "."})

    assert result.status == "success"
    assert result.result["matches"] == []
