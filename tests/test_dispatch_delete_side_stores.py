"""A dispatched delete must drop the side stores, the way the HTTP route does.

A session leaves three places, not one. The conversation store is the obvious
one, and both delete paths clear it. The other two live in
``project_store`` and ``session_prefs``, which namespace their rows by Agent::

    def _session_key(session_id, agent_id):
        return f"{agent_id or 'default'}::{session_id}"

``SessionDetailHandler.DELETE`` clears those two, wrapped in a best-effort
``try`` so a locked store cannot fail the delete. ``SessionService`` — the
object behind ``dispatch("delete_session")``, which the cloud console drives
over the history channel — clears neither, so a delete from there leaves the
project binding and the pinned model behind while reporting success.

Both leftovers outlive the session. A surviving project binding keeps counting
the deleted session in the "spaces in use" figure the session list groups by and
keeps the Agent's file tools pointed at a project the user removed; a surviving
model pin answers for that Agent the next time the id is reused.

These tests drive the real ``dispatch`` and read the stores back off disk.
"""

import json
import os

import pytest


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A SessionService whose Agent exists and whose stores live in tmp_path."""
    from agent.registry import AgentProfile, AgentRegistry
    import agent.registry as registry_module
    from agent.workspace import project_store, session_prefs
    import common.state_dir as state_dir
    from agent.chat.session_service import SessionService

    # shared_root is imported inside each store's _store_file(), so the patch
    # has to land on common.state_dir itself.
    monkeypatch.setattr(state_dir, "shared_root", lambda *a, **k: tmp_path)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    registry = AgentRegistry(
        [AgentProfile("research", "Research", str(workspace))], "research"
    )
    monkeypatch.setattr(registry_module, "get_agent_registry", lambda: registry)

    class FakeStore:
        def __init__(self):
            self.cleared = []

        def clear_session(self, session_id):
            self.cleared.append(session_id)
            return 0

    store = FakeStore()
    import agent.memory as memory_module

    monkeypatch.setattr(memory_module, "get_conversation_store", lambda *_a, **_k: store)

    def rows(module):
        path = module._store_file()
        if not os.path.isfile(path):
            return {}
        return json.loads(open(path, encoding="utf-8").read()).get("sessions", {})

    return SessionService(), store, project_store, session_prefs, rows


def _seed(project_store, session_prefs, session_id, agent_id, project):
    project_store.set_project_dir(session_id, project, agent_id=agent_id)
    session_prefs.set_prefs(session_id, agent_id=agent_id, model="claude-sonnet-5")


def test_dispatched_delete_drops_the_side_stores(wired, tmp_path):
    service, store, project_store, session_prefs, rows = wired
    session_id = "session_dispatched"
    project = tmp_path / "proj"
    project.mkdir()
    _seed(project_store, session_prefs, session_id, "research", str(project))

    result = service.dispatch(
        "delete_session", {"session_id": session_id, "agent_id": "research"}
    )

    assert result["code"] == 200
    # The conversation store is what the old code already cleared.
    assert store.cleared
    # The two it did not.
    assert rows(project_store) == {}
    assert rows(session_prefs) == {}


def test_a_dispatched_delete_leaves_nothing_readable(wired, tmp_path):
    service, _store, project_store, session_prefs, _rows = wired
    session_id = "session_gone"
    project = tmp_path / "proj"
    project.mkdir()
    _seed(project_store, session_prefs, session_id, "research", str(project))

    service.dispatch("delete_session", {"session_id": session_id, "agent_id": "research"})

    assert project_store.get_project_dir(session_id, agent_id="research") is None
    assert session_prefs.get_prefs(session_id, agent_id="research") == {}


def test_the_service_level_delete_drops_them_too(wired, tmp_path):
    """delete_session() is the same defect one layer down; it is not dispatch's."""
    service, _store, project_store, session_prefs, rows = wired
    session_id = "session_direct"
    project = tmp_path / "proj"
    project.mkdir()
    _seed(project_store, session_prefs, session_id, "research", str(project))

    service.delete_session(session_id, agent_id="research")

    assert rows(project_store) == {}
    assert rows(session_prefs) == {}


def test_only_the_named_agents_rows_go(wired, tmp_path):
    service, _store, project_store, session_prefs, rows = wired
    session_id = "session_shared"
    for agent_id, folder in (("research", "p1"), ("other", "p2")):
        project = tmp_path / folder
        project.mkdir()
        _seed(project_store, session_prefs, session_id, agent_id, str(project))

    service.delete_session(session_id, agent_id="research")

    # "other" is not in the registry, so its row is untouched either way — what
    # matters is that the delete did not sweep every Agent's row.
    assert f"research::{session_id}" not in rows(project_store)
    assert f"other::{session_id}" in rows(project_store)


def test_a_locked_side_store_does_not_fail_the_delete(wired, tmp_path, monkeypatch):
    """Both stores are best-effort on the HTTP route; keep that here."""
    service, store, project_store, session_prefs, rows = wired
    session_id = "session_locked"
    project = tmp_path / "proj"
    project.mkdir()
    _seed(project_store, session_prefs, session_id, "research", str(project))

    import agent.workspace.session_prefs as prefs_module

    def boom(*_a, **_k):
        raise OSError("store is locked")

    monkeypatch.setattr(prefs_module, "forget_session", boom)

    result = service.dispatch(
        "delete_session", {"session_id": session_id, "agent_id": "research"}
    )

    assert result["code"] == 200
    assert store.cleared
    # The store that did work is still cleaned up.
    assert rows(project_store) == {}


def test_deleting_a_session_with_nothing_bound_still_succeeds(wired):
    service, store, project_store, session_prefs, rows = wired

    result = service.dispatch(
        "delete_session", {"session_id": "never-existed", "agent_id": "research"}
    )

    assert result["code"] == 200
    assert store.cleared
    assert rows(project_store) == {}
    assert rows(session_prefs) == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
