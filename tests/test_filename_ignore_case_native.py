import pytest

from agent.tools.search_files.search_files import SearchFiles


@pytest.mark.parametrize("pattern", ["report", "*.md", "r[ae]port.*"])
def test_ignore_case_finds_mixed_case_real_filenames(tmp_path, pattern):
    folder = tmp_path / "nested"
    folder.mkdir()
    (folder / "REPORT.MD").write_text("notes")
    tool = SearchFiles({"cwd": str(tmp_path)})
    result = tool.execute({"pattern": pattern, "target": "files", "ignore_case": True})
    assert result.status == "success"
    assert result.result["files"] == ["nested/REPORT.MD"]


def test_case_sensitive_filename_search_stays_exact(tmp_path):
    (tmp_path / "REPORT.MD").write_text("notes")
    tool = SearchFiles({"cwd": str(tmp_path)})
    result = tool.execute({"pattern": "report", "target": "files", "ignore_case": False})
    assert result.result["files"] == []
