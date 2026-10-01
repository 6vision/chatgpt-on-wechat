"""A real external regex failure must reach the existing Python fallback."""

import os
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


@pytest.mark.skipif(shutil.which("rg") is None, reason="requires the real ripgrep executable")
@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root can read any file")
def test_ripgrep_partial_results_survive_an_unreadable_file(tmp_path):
    (tmp_path / "record.txt").write_text("id=42;\n", encoding="utf-8")
    locked = tmp_path / "locked.txt"
    locked.write_text("id=7;\n", encoding="utf-8")
    locked.chmod(0)
    tool = SearchFiles({"cwd": str(tmp_path)})
    tool._pick_backend = lambda: tool._backend_rg
    # The fallback would find the same row; what must not happen is a full
    # rescan in Python just because one file could not be read.
    tool._backend_python = lambda opts: pytest.fail("fell back to python")

    try:
        result = tool.execute({"pattern": "id=", "path": "."})
    finally:
        locked.chmod(0o644)

    assert result.status == "success"
    assert result.result["matches"] == [{"file": "record.txt", "line": 1, "match": "id=42;"}]
