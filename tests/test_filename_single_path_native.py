from agent.tools.search_files.search_files import SearchFiles


def test_explicit_file_search_never_includes_nested_namesakes(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("main")
    folder = tmp_path / "unrelated"
    folder.mkdir()
    (folder / "notes.md").write_text("other")
    tool = SearchFiles({"cwd": str(tmp_path)})
    result = tool.execute({"pattern": "*.md", "target": "files", "path": str(target)})
    assert result.status == "success"
    assert result.result["files"] == ["notes.md"]
    assert result.result["match_count"] == 1


def test_directory_search_still_includes_nested_namesakes(tmp_path):
    (tmp_path / "notes.md").write_text("main")
    folder = tmp_path / "unrelated"
    folder.mkdir()
    (folder / "notes.md").write_text("other")
    result = SearchFiles({"cwd": str(tmp_path)}).execute({"pattern": "*.md", "target": "files"})
    assert set(result.result["files"]) == {"notes.md", "unrelated/notes.md"}
