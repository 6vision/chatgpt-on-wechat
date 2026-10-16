"""Project changes report storage failures and retain the last saved state."""

import errno
import json
from pathlib import Path

import pytest
import web

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from agent.workspace import project_store, session_prefs
from channel.web.api import workspace


@pytest.fixture
def projects(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    primary.mkdir()
    folders = [tmp_path / name for name in ("old", "new")]
    for folder in folders:
        folder.mkdir()
    set_agent_registry(AgentRegistry([
        AgentProfile("primary", "Primary", str(primary)),
    ], default_agent_id="primary"))
    project_store.set_project_dir("chat", str(folders[0]))
    project_store.rename_project(str(folders[0]), "Saved name")
    project_store.set_order([str(folders[0])])
    store = Path(project_store._store_file())
    original = store.read_bytes()
    monkeypatch.setattr(workspace, "_require_auth", lambda: None)
    app = web.application(("/select", "ProjectSelectHandler"), vars(workspace))
    try:
        yield app, store, original, folders
    finally:
        set_agent_registry(None)


def _fail_during_serialization(monkeypatch):
    def disk_full(data, stream, *args, **kwargs):
        stream.write('{"sessions":')
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(json, "dump", disk_full)


def test_http_selection_reports_disk_failure_and_keeps_previous_binding(projects, monkeypatch):
    app, store, original, folders = projects
    _fail_during_serialization(monkeypatch)
    response = app.request("/select", method="POST", data=json.dumps({
        "session": "chat", "project_dir": str(folders[1]),
    }))
    assert response.status == "200 OK"
    result = json.loads(response.data)
    assert result["status"] == "error"
    assert "No space left" in result["message"]
    assert store.read_bytes() == original
    assert project_store.get_project_dir("chat") == str(folders[0])


@pytest.mark.parametrize("operation", ["select", "clear", "rename", "order", "delete"])
def test_failed_mutations_raise_without_leaving_partial_staging_files(projects, monkeypatch, operation):
    _, store, original, folders = projects
    _fail_during_serialization(monkeypatch)
    mutations = {
        "select": lambda: project_store.set_project_dir("chat", str(folders[1])),
        "clear": lambda: project_store.set_project_dir("chat", None),
        "rename": lambda: project_store.rename_project(str(folders[0]), "Unsaved name"),
        "order": lambda: project_store.set_order([str(folders[1])]),
        "delete": lambda: project_store.delete_project(str(folders[0])),
    }
    with pytest.raises(OSError, match="No space left"):
        mutations[operation]()
    assert store.read_bytes() == original
    assert list(store.parent.glob("*.tmp")) == []
    assert list(store.parent.glob(".*.tmp")) == []


def test_successful_selection_remains_persistent(projects):
    _, _, _, folders = projects
    assert project_store.set_project_dir("chat", str(folders[1])) == str(folders[1])
    assert project_store.get_project_dir("chat") == str(folders[1])
    assert project_store.list_recents()[0]["path"] == str(folders[1])


@pytest.mark.parametrize("operation", ["set", "clear", "forget"])
def test_session_preferences_failures_preserve_saved_overrides(projects, monkeypatch, operation):
    session_prefs.set_prefs("chat", "primary", permission="read-only", model="saved-model")
    store = Path(session_prefs._store_file())
    original = store.read_bytes()
    _fail_during_serialization(monkeypatch)
    mutations = {
        "set": lambda: session_prefs.set_prefs("chat", "primary", permission="full-access"),
        "clear": lambda: session_prefs.set_prefs("chat", "primary", permission=None, model=None),
        "forget": lambda: session_prefs.forget_agent("primary"),
    }
    with pytest.raises(OSError, match="No space left"):
        mutations[operation]()
    assert store.read_bytes() == original
    assert session_prefs.get_prefs("chat", "primary")["permission"] == "read-only"
    assert list(store.parent.glob("*.tmp")) == []
    assert list(store.parent.glob(".*.tmp")) == []


def test_unchanged_session_preferences_keep_the_existing_api(projects):
    assert session_prefs.set_prefs("chat", "primary", model="selected-model") == {"model": "selected-model"}
    assert session_prefs.get_prefs("chat", "primary")["model"] == "selected-model"
