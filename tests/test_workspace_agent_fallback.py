"""A project-scoped request uses the named Agent's system workspace."""

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
import web

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from agent.workspace import project_store
from channel.web.api import workspace
from channel.web.core import _common


@pytest.fixture
def console(tmp_path, monkeypatch):
    # Resolve preview-token storage inside the fixture as well as Agent data.
    data_root = tmp_path / "app-data"
    data_root.mkdir()
    monkeypatch.setattr(_common, "get_data_root", lambda: str(data_root))
    monkeypatch.setattr(_common, "_PREVIEW_SECRET", None)
    roots = {name: tmp_path / name for name in ("primary", "writer", "project")}
    for name, root in roots.items():
        root.mkdir()
        if name != "project":
            (root / "MEMORY.md").write_text(f"{name} notes\n", encoding="utf-8")
    registry = AgentRegistry([
        AgentProfile("primary", "Primary", str(roots["primary"])),
        AgentProfile("writer", "Writer", str(roots["writer"])),
    ], default_agent_id="primary")
    set_agent_registry(registry)
    project_store.set_project_dir("chat", str(roots["project"]), "writer")
    monkeypatch.setattr(workspace, "_require_auth", lambda: None)
    monkeypatch.setattr(workspace, "_mark_memory_dirty", lambda agent_id=None: None)
    app = web.application((
        "/read", "WorkspaceReadHandler", "/write", "WorkspaceWriteHandler",
        "/resolve", "WorkspaceResolveHandler",
    ), vars(workspace))
    try:
        yield app, roots
    finally:
        set_agent_registry(None)


@pytest.mark.parametrize("key", ["agent", "agent_id"])
def test_project_editor_reads_and_saves_the_requested_agents_memory(console, key):
    app, roots = console
    query = urlencode({"path": "MEMORY.md", "session": "chat", key: "writer"})
    loaded = json.loads(app.request("/read?" + query).data)
    assert loaded["status"] == "success"
    assert loaded["content"] == "writer notes\n"
    result = json.loads(app.request("/write", method="POST", data=json.dumps({
        "path": "MEMORY.md", "session": "chat", key: "writer", "content": "updated writer notes\n",
        "expected_mtime": loaded["mtime"],
    })).data)
    assert result["status"] == "success"
    assert (roots["writer"] / "MEMORY.md").read_text() == "updated writer notes\n"
    assert (roots["primary"] / "MEMORY.md").read_text() == "primary notes\n"


def test_system_file_resolver_uses_the_requested_agent(console):
    app, roots = console
    query = urlencode({"path": "MEMORY.md", "session": "chat", "agent_id": "writer"})
    result = json.loads(app.request("/resolve?" + query).data)
    assert result["status"] == "success"
    assert Path(result["file"]["abs_path"]) == roots["writer"] / "MEMORY.md"


def test_absolute_system_path_under_the_requested_agent_remains_editable(console):
    app, roots = console
    query = urlencode({"path": str(roots["writer"] / "MEMORY.md"), "session": "chat", "agent_id": "writer"})
    result = json.loads(app.request("/read?" + query).data)
    assert result["status"] == "success"
    assert result["content"] == "writer notes\n"


def test_project_copy_and_default_agent_controls(console):
    app, roots = console
    (roots["project"] / "MEMORY.md").write_text("project-local notes\n", encoding="utf-8")
    query = urlencode({"path": "MEMORY.md", "session": "chat", "agent_id": "writer"})
    result = json.loads(app.request("/read?" + query).data)
    assert result["content"] == "project-local notes\n"
    default = json.loads(app.request("/read?path=MEMORY.md").data)
    assert default["content"] == "primary notes\n"
