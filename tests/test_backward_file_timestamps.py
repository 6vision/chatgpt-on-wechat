"""Native preserved-timestamp copies must still invalidate a prior file view."""

import os
import shutil

import pytest

from agent.tools.edit.edit import Edit
from agent.tools.read.read import Read
from agent.tools.utils.file_state import reset
from agent.tools.write.write import Write


@pytest.mark.parametrize("tool_name", ["edit", "write"])
@pytest.mark.parametrize("replacement_time", [1_700_000_000, 1_700_000_200])
def test_native_copy_with_changed_mtime_warns(tmp_path, tool_name, replacement_time):
    reset()
    target = tmp_path / "target.txt"
    source = tmp_path / "previous.txt"
    target.write_text("first line\nsecond line\n", encoding="utf-8")
    source.write_text("first line\nexternal change\n", encoding="utf-8")
    os.utime(target, (1_700_000_100, 1_700_000_100))
    os.utime(source, (replacement_time, replacement_time))
    assert Read({"cwd": str(tmp_path)}).execute({"path": str(target)}).status == "success"
    # copy2 is a real restore/copy operation that preserves the older file's metadata.
    shutil.copy2(source, target)
    assert target.stat().st_mtime == replacement_time
    if tool_name == "edit":
        result = Edit({"cwd": str(tmp_path)}).execute(
            {"path": str(target), "oldText": "first line", "newText": "edited first line"}
        )
    else:
        result = Write({"cwd": str(tmp_path)}).execute(
            {"path": str(target), "content": "new content\n"}
        )
    assert result.status == "success", result.result
    assert "modified after you last read it" in result.result["warning"]
    if tool_name == "edit":
        assert target.read_text(encoding="utf-8") == "edited first line\nexternal change\n"
    else:
        assert target.read_text(encoding="utf-8") == "new content\n"
    # A successful tool write makes its view current again.
    from agent.tools.utils.file_state import staleness_warning
    assert staleness_warning(str(target)) is None


@pytest.mark.parametrize("tool_name", ["edit", "write"])
def test_unchanged_file_still_has_no_warning(tmp_path, tool_name):
    reset()
    target = tmp_path / "target.txt"
    target.write_text("original text\n", encoding="utf-8")
    assert Read({"cwd": str(tmp_path)}).execute({"path": str(target)}).status == "success"
    if tool_name == "edit":
        result = Edit({"cwd": str(tmp_path)}).execute(
            {"path": str(target), "oldText": "original", "newText": "edited"}
        )
    else:
        result = Write({"cwd": str(tmp_path)}).execute(
            {"path": str(target), "content": "new text\n"}
        )
    assert result.status == "success", result.result
    assert "warning" not in result.result
