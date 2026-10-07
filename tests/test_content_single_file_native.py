"""Explicit file paths scope actual content-search backends to that one file."""

import os
import shutil

import pytest

from agent.tools.search_files.search_files import SearchFiles


@pytest.mark.parametrize("backend", ["rg", "grep", "python"])
@pytest.mark.parametrize("mode", ["content", "files", "count"])
@pytest.mark.parametrize("single_file", [True, False])
def test_content_search_scope_is_identical_for_native_file_and_directory_inputs(
    tmp_path, monkeypatch, backend, mode, single_file
):
    binary = shutil.which(backend) if backend != "python" else None
    if backend != "python" and (os.name == "nt" or not binary):
        pytest.skip("native POSIX search binary unavailable")
    source = tmp_path / "source"
    source.mkdir()
    unrelated = source / "unrelated"
    unrelated.mkdir()
    selected = source / "notes.md"
    selected.write_text("TARGET selected\n", encoding="utf-8")
    (unrelated / "notes.md").write_text("TARGET namesake\n", encoding="utf-8")
    (unrelated / "other.md").write_text("TARGET other\n", encoding="utf-8")
    native_bin = tmp_path / "bin"
    native_bin.mkdir()
    if binary:
        (native_bin / backend).symlink_to(binary)
    monkeypatch.setenv("PATH", str(native_bin))
    tool = SearchFiles({"cwd": str(source)})
    assert tool._pick_backend().__name__ == "_backend_" + backend
    result = tool.execute({"pattern": "TARGET", "path": str(selected if single_file else source), "output_mode": mode})
    assert result.status == "success", result.result
    files = ["notes.md"] if single_file else ["notes.md", "unrelated/notes.md", "unrelated/other.md"]
    assert result.result["match_count"] == len(files)
    if mode == "files":
        assert result.result["files"] == files
    elif mode == "count":
        assert result.result["counts"] == [{"file": file, "count": 1} for file in files]
    else:
        contents = ["TARGET selected"] if single_file else ["TARGET selected", "TARGET namesake", "TARGET other"]
        assert result.result["matches"] == [
            {"file": file, "line": 1, "match": text} for file, text in zip(files, contents)
        ]
