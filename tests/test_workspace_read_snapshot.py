"""An editor baseline describes the file descriptor whose bytes were read."""

import builtins
import json
import os

import pytest
import web

from agent.workspace.service import WorkspaceConflictError, WorkspaceService
from channel.web.api import workspace


@pytest.fixture
def replaced_read(tmp_path, monkeypatch):
    target = tmp_path / "notes.md"
    target.write_bytes(b"original notes\n")
    old_time = 1_900_000_000.0
    os.utime(target, (old_time, old_time))
    replacement = tmp_path / "new-notes.md"
    replacement.write_bytes(b"newer notes from the agent\n")
    os.utime(replacement, (old_time + 60, old_time + 60))
    real_open = builtins.open

    class ReplacingReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, *args):
            raw = self.stream.read(*args)
            # The agent's atomic writer replaces the path after our read,
            # leaving this open descriptor attached to the older file.
            os.replace(replacement, target)
            return raw

    def open_with_replacement(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        if os.fspath(path) == str(target) and mode == "rb" and replacement.exists():
            return ReplacingReader(stream)
        return stream

    monkeypatch.setattr(builtins, "open", open_with_replacement)
    return WorkspaceService(str(tmp_path)), target, old_time


def test_read_metadata_belongs_to_the_returned_content(replaced_read):
    service, target, old_time = replaced_read
    loaded = service.read_text("notes.md")
    assert loaded["content"] == "original notes\n"
    assert loaded["mtime"] == old_time
    assert loaded["size"] == len(b"original notes\n")
    assert target.read_bytes() == b"newer notes from the agent\n"
    with pytest.raises(WorkspaceConflictError):
        service.write_text("notes.md", "my edit\n", expected_mtime=loaded["mtime"])
    assert target.read_bytes() == b"newer notes from the agent\n"


def test_http_editor_reports_conflict_after_atomic_replacement(replaced_read, monkeypatch):
    service, target, _ = replaced_read
    monkeypatch.setattr(workspace, "_require_auth", lambda: None)
    monkeypatch.setattr(workspace, "_editable_target", lambda *args: (service, "notes.md"))
    app = web.application(("/read", "WorkspaceReadHandler", "/write", "WorkspaceWriteHandler"), vars(workspace))
    response = app.request("/read?path=notes.md")
    assert response.status == "200 OK"
    loaded = json.loads(response.data)
    assert loaded["status"] == "success"
    response = app.request("/write", method="POST", data=json.dumps({
        "path": "notes.md", "content": "my edit\n", "expected_mtime": loaded["mtime"],
    }))
    result = json.loads(response.data)
    assert result["status"] == "error"
    assert result["code"] == "conflict"
    assert target.read_bytes() == b"newer notes from the agent\n"


def test_unchanged_file_keeps_the_existing_editor_round_trip(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("old\n", encoding="utf-8")
    service = WorkspaceService(str(tmp_path))
    loaded = service.read_text("notes.md")
    assert loaded["mtime"] == target.stat().st_mtime
    service.write_text("notes.md", "edited\n", expected_mtime=loaded["mtime"])
    assert target.read_text(encoding="utf-8") == "edited\n"
