"""Deleting a team conversation deletes every local participant's copy."""

import pytest


class _Profile:
    def __init__(self, agent_id, workspace, name=None):
        self.id = agent_id
        self.workspace = str(workspace)
        self.name = name or agent_id


@pytest.fixture
def team(tmp_path, monkeypatch):
    """Two Agents on one shared conversation store, plus a roster naming both."""
    import agent.registry as registry_module
    from agent.memory import conversation_store as cs
    from agent.workspace import session_prefs

    default_ws = tmp_path / "agents" / "alpha"
    beta_ws = tmp_path / "agents" / "beta"
    for path in (default_ws, beta_ws):
        (path / "memory").mkdir(parents=True)

    class _Registry:
        default_agent_id = "alpha"

        def list(self, include_disabled=True):
            return [_Profile("alpha", default_ws), _Profile("beta", beta_ws)]

        def get(self, agent_id=None, require_enabled=True):
            wanted = agent_id or "alpha"
            for profile in self.list():
                if profile.id == wanted:
                    return profile
            raise KeyError(agent_id)

        def get_addressed(self, agent_id, require_enabled=True):
            return self.get(agent_id)

    monkeypatch.setattr(registry_module, "get_agent_registry", lambda: _Registry())
    monkeypatch.setattr(cs, "_store_instances", {})
    monkeypatch.setattr(cs, "_store_instance", None)

    db_path, alpha_id = cs._resolve_global_binding(default_ws)
    alpha = cs.ConversationStore(db_path, alpha_id)
    beta = cs.ConversationStore(db_path, "beta")

    session_id = "session_team_1"
    for store, view in ((alpha, "alpha"), (beta, "beta")):
        store.append_messages(
            session_id=session_id,
            channel_type="team",
            messages=[
                {"role": "user", "content": "the shared question"},
                {"role": "assistant", "content": f"{view} private view"},
            ],
        )
    session_prefs.set_prefs(session_id, agent_id="alpha", members=["beta"])

    return {
        "db_path": db_path,
        "alpha_id": alpha_id,
        "alpha": alpha,
        "beta": beta,
        "session_id": session_id,
        "default_agent_id": "alpha",
    }


@pytest.fixture
def service(team, monkeypatch):
    """A SessionService whose store lookup resolves the default Agent's id."""
    from agent.chat.session_service import SessionService
    from agent.memory import conversation_store as cs

    handle = SessionService.__new__(SessionService)
    default_id = team["default_agent_id"]

    def _store_for(agent_id=None):
        wanted = agent_id or default_id
        return cs.ConversationStore(team["db_path"],
                                    "" if wanted == default_id else wanted)

    monkeypatch.setattr(SessionService, "_get_store", lambda self, agent_id=None: _store_for(agent_id))
    monkeypatch.setattr(SessionService, "_remove_agent", lambda *a, **k: None)
    monkeypatch.setattr(SessionService, "_cancel_running", lambda *a, **k: 0)
    return handle


def _messages(store, session_id):
    return [m.get("content") for m in store.load_messages(session_id)]


def _listed(store, session_id):
    return session_id in store.list_session_ids()


def test_delete_clears_every_participant(service, team):
    session_id = team["session_id"]

    service.delete_session(session_id, agent_id="alpha")

    assert _messages(team["alpha"], session_id) == []
    assert _messages(team["beta"], session_id) == []
    assert not _listed(team["beta"], session_id)


def test_a_solo_session_is_unaffected(service, team):
    from agent.workspace import session_prefs

    solo = "session_solo_1"
    team["alpha"].append_messages(
        session_id=solo, channel_type="web",
        messages=[{"role": "user", "content": "just mine"}],
    )
    session_prefs.set_prefs(solo, agent_id="alpha", members=[])

    service.delete_session(solo, agent_id="alpha")

    assert _messages(team["alpha"], solo) == []
    assert _messages(team["beta"], team["session_id"])


def test_a_failing_teammate_does_not_fail_the_delete(service, team, monkeypatch):
    from agent.chat.session_service import SessionService
    from agent.memory import conversation_store as cs

    def _store_for(agent_id=None):
        if agent_id == "beta":
            raise RuntimeError("unavailable")
        return cs.ConversationStore(team["db_path"], team["alpha_id"])

    monkeypatch.setattr(SessionService, "_get_store", lambda self, agent_id=None: _store_for(agent_id))
    service.delete_session(team["session_id"], agent_id="alpha")
    assert _messages(team["alpha"], team["session_id"]) == []


def test_the_fanout_does_not_recurse(service, team, monkeypatch):
    from agent.chat.session_service import SessionService

    seen = []
    original = SessionService.delete_session

    def _counting(self, session_id, agent_id=None, fanout=True):
        seen.append((agent_id, fanout))
        return original(self, session_id, agent_id=agent_id, fanout=fanout)

    monkeypatch.setattr(SessionService, "delete_session", _counting)
    service.delete_session(team["session_id"], agent_id="alpha")
    assert seen == [("alpha", True), ("beta", False)]


def test_the_web_delete_fans_out_too(service, team, monkeypatch):
    import json
    import types
    from unittest.mock import patch

    from channel.web.api import sessions as sessions_api

    class _Channel:
        session_queues = {}

        def cancel_session(self, *a, **k):
            pass

        def _session_queue_key(self, *a):
            return "k"

    session_id = team["session_id"]
    with patch.object(sessions_api, "_require_auth"), \
         patch.object(sessions_api.web, "header", lambda *a, **k: None), \
         patch.object(sessions_api.web, "input", lambda **k: types.SimpleNamespace(agent_id="alpha")), \
         patch.object(sessions_api, "WebChannel", _Channel), \
         patch("agent.memory.get_conversation_store", lambda *a, **k: team["alpha"]):
        response = json.loads(sessions_api.SessionDetailHandler().DELETE(session_id))

    assert response["status"] == "success"
    assert _messages(team["beta"], session_id) == []
