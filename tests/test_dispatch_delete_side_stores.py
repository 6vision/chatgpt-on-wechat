"""Pin that SessionService deletes (dispatched or direct) drop the project/prefs side stores."""

import json
import os

import pytest

SID = "session_x"


@pytest.fixture
def wired(tmp_path, monkeypatch):
    import agent.memory as memory_module
    import agent.registry as registry_module
    import common.state_dir as state_dir
    from agent.chat.session_service import SessionService
    from agent.registry import AgentProfile, AgentRegistry
    from agent.workspace import project_store, session_prefs

    # shared_root is imported at call time inside each store's _store_file().
    monkeypatch.setattr(state_dir, "shared_root", lambda *a, **k: tmp_path)
    registry = AgentRegistry([AgentProfile("research", "Research", str(tmp_path))], "research")
    monkeypatch.setattr(registry_module, "get_agent_registry", lambda: registry)
    cleared = []
    store = type("FakeStore", (), {"clear_session": lambda self, sid: cleared.append(sid) or 0})()
    monkeypatch.setattr(memory_module, "get_conversation_store", lambda *_a, **_k: store)

    def seed(agent_id="research", folder="proj"):
        (tmp_path / folder).mkdir()
        project_store.set_project_dir(SID, str(tmp_path / folder), agent_id=agent_id)
        session_prefs.set_prefs(SID, agent_id=agent_id, model="claude-sonnet-5")

    def rows(module):
        path = module._store_file()
        return json.loads(open(path, encoding="utf-8").read()).get("sessions", {}) if os.path.isfile(path) else {}

    return SessionService(), cleared, seed, rows, project_store, session_prefs


def _dispatch(service):
    return service.dispatch("delete_session", {"session_id": SID, "agent_id": "research"})


@pytest.mark.parametrize("via_dispatch, seeded", [(True, True), (False, True), (True, False)])
def test_delete_drops_side_stores(wired, via_dispatch, seeded):
    service, cleared, seed, rows, project_store, session_prefs = wired
    if seeded:
        seed()

    if via_dispatch:
        assert _dispatch(service)["code"] == 200 and cleared
    else:
        service.delete_session(SID, agent_id="research")

    assert rows(project_store) == {} and rows(session_prefs) == {}
    assert project_store.get_project_dir(SID, agent_id="research") is None
    assert session_prefs.get_prefs(SID, agent_id="research") == {}


def test_only_the_named_agents_rows_go(wired):
    service, _cleared, seed, rows, project_store, _prefs = wired
    seed("research", "p1")
    seed("other", "p2")

    service.delete_session(SID, agent_id="research")

    assert list(rows(project_store)) == [f"other::{SID}"]


def test_locked_side_store_does_not_fail_delete(wired, monkeypatch):
    import agent.workspace.session_prefs as prefs_module

    service, cleared, seed, rows, project_store, _prefs = wired
    seed()

    def locked(*_a, **_k):
        raise OSError("store is locked")

    monkeypatch.setattr(prefs_module, "forget_session", locked)

    assert _dispatch(service)["code"] == 200 and cleared
    assert rows(project_store) == {}
