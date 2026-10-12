"""Pin that the HTTP session DELETE drops the project/prefs rows of the Agent the session belongs to."""

import json
import os

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agent.memory as memory_module
    import bridge.bridge as bridge_module
    import channel.web.api.sessions as sessions_api
    import common.state_dir as state_dir
    from agent.workspace import project_store, session_prefs

    # shared_root is imported at call time inside each store's _store_file().
    monkeypatch.setattr(state_dir, "shared_root", lambda *a, **k: tmp_path)
    scoped = staticmethod(lambda sid, agent_id=None: f"{agent_id or 'default'}::{sid}")
    noop = staticmethod(lambda *_a, **_k: None)
    channel = type("FakeChannel", (), {"session_queues": {}, "cancel_session": noop, "_session_queue_key": scoped})
    agent_bridge = type("FakeAgentBridge", (), {"scoped_session_key": scoped, "clear_session": noop})
    bridge = type("FakeBridge", (), {"get_agent_bridge": staticmethod(agent_bridge)})
    store = type("FakeStore", (), {"clear_session": noop})
    monkeypatch.setattr(sessions_api, "_require_auth", lambda: None)
    monkeypatch.setattr(sessions_api, "_request_agent_id", lambda p: p.get("agent_id") or None)
    monkeypatch.setattr(sessions_api, "_get_workspace_root", lambda agent_id=None: str(tmp_path))
    monkeypatch.setattr(sessions_api.web, "header", lambda *_a, **_k: None)
    monkeypatch.setattr(sessions_api, "WebChannel", channel)
    monkeypatch.setattr(bridge_module, "Bridge", bridge)
    monkeypatch.setattr(memory_module, "get_conversation_store", lambda *_a, **_k: store)

    def delete(session_id, agent_id):
        monkeypatch.setattr(sessions_api.web, "input", lambda **_k: {"agent_id": agent_id or ""})
        return json.loads(sessions_api.SessionDetailHandler().DELETE(session_id))["status"]

    def seed(agent_id, folder="proj"):
        (tmp_path / folder).mkdir()
        project_store.set_project_dir("sess", str(tmp_path / folder), agent_id=agent_id)
        session_prefs.set_prefs("sess", agent_id=agent_id, model="claude-sonnet-5")

    def rows(module):
        path = module._store_file()
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("sessions", {})

    return delete, seed, rows, project_store, session_prefs


@pytest.mark.parametrize("agent_id", ["research", None])
def test_delete_drops_that_agents_rows(env, agent_id):
    delete, seed, rows, project_store, session_prefs = env
    seed(agent_id)
    key = f"{agent_id or 'default'}::sess"
    assert key in rows(project_store) and key in rows(session_prefs)

    assert delete("sess", agent_id) == "success"

    assert key not in rows(project_store) and key not in rows(session_prefs)
    assert project_store.get_project_dir("sess", agent_id=agent_id) is None
    assert session_prefs.get_prefs("sess", agent_id=agent_id) == {}


def test_delete_leaves_other_agents_rows(env):
    delete, seed, rows, project_store, session_prefs = env
    seed("research", "p1")
    seed("writer", "p2")

    delete("sess", "research")

    assert list(rows(project_store)) == list(rows(session_prefs)) == ["writer::sess"]
    assert session_prefs.get_prefs("sess", agent_id="writer") == {"model": "claude-sonnet-5"}


def test_delete_with_nothing_bound_succeeds(env):
    delete, _seed, rows, project_store, session_prefs = env

    assert delete("never-existed", "research") == "success"
    assert rows(project_store) == {} and rows(session_prefs) == {}


def test_failed_side_store_cleanup_does_not_fail_delete(env, monkeypatch):
    import agent.workspace.session_prefs as prefs_module

    delete, seed, _rows, _ps, _sp = env
    seed("research")

    def locked(*_a, **_k):
        raise OSError("store is locked")

    monkeypatch.setattr(prefs_module, "forget_session", locked)

    assert delete("sess", "research") == "success"
