"""Deleting a session must drop the side stores of the Agent it belonged to.

``project_store`` and ``session_prefs`` both namespace their rows by Agent::

    def _session_key(session_id, agent_id):
        return f"{agent_id or 'default'}::{session_id}"

``SessionDetailHandler.DELETE`` knows which Agent the session is on — it reads
``agent_id`` from the request and uses it for the conversation store, the cancel
key and the queue key — but called ``forget_session(session_id)`` without it, so
both lookups resolved to ``default::<id>`` and dropped a row that does not exist.
The real row survived.

What is left behind is not inert. A surviving project binding keeps the deleted
session counted in the "spaces in use" figure the session list groups by, and
keeps pointing that Agent's file tools at a project the user removed. A
surviving ``model`` pin keeps answering for it, so the next run on a freshly
recreated session id silently uses a model the user never went back for.

These tests drive the real handler, so they fail on the old call and pass on the
fixed one.
"""

import json
import os

import pytest


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Point both side stores at a temp dir; hand back read helpers.

    ``shared_root`` is imported inside each store's ``_store_file()``, so the
    patch has to land on ``common.state_dir`` itself — the import resolves at
    call time.
    """
    from agent.workspace import project_store, session_prefs
    import common.state_dir as state_dir

    monkeypatch.setattr(state_dir, "shared_root", lambda *a, **k: tmp_path)

    def rows(module):
        path = module._store_file()
        if not os.path.isfile(path):
            return {}
        return json.loads(open(path, encoding="utf-8").read()).get("sessions", {})

    return project_store, session_prefs, rows


@pytest.fixture
def delete_session(monkeypatch):
    """Call the real DELETE handler with the side effects stubbed out.

    Only the parts that are not under test are replaced: auth, the request
    parsing, the conversation store, the channel queue and the AgentBridge
    instance. The side-store cleanup runs for real.
    """
    import channel.web.api.sessions as sessions_api

    monkeypatch.setattr(sessions_api, "_require_auth", lambda: None)
    monkeypatch.setattr(
        sessions_api, "_request_agent_id", lambda params: params.get("agent_id") or None
    )

    class FakeWeb:
        @staticmethod
        def header(*_a, **_k):
            pass

        @staticmethod
        def input(**kwargs):
            return dict(kwargs)

    monkeypatch.setattr(sessions_api.web, "header", FakeWeb.header)
    monkeypatch.setattr(sessions_api.web, "input", FakeWeb.input)
    monkeypatch.setattr(
        sessions_api, "_get_workspace_root", lambda agent_id=None: str(_tmp_workspace)
    )

    class FakeStore:
        @staticmethod
        def clear_session(_sid):
            return None

    import agent.memory as memory_module

    monkeypatch.setattr(
        memory_module, "get_conversation_store", lambda *_a, **_k: FakeStore()
    )

    class FakeChannel:
        session_queues = {}

        @staticmethod
        def cancel_session(*_a, **_k):
            return None

        @staticmethod
        def _session_queue_key(session_id, agent_id=None):
            return f"{agent_id or 'default'}::{session_id}"

    monkeypatch.setattr(sessions_api, "WebChannel", FakeChannel)

    class FakeAgentBridge:
        @staticmethod
        def scoped_session_key(session_id, agent_id=None):
            return f"{agent_id or 'default'}::{session_id}"

        @staticmethod
        def clear_session(*_a, **_k):
            return None

    class FakeBridge:
        @staticmethod
        def get_agent_bridge():
            return FakeAgentBridge()

    import bridge.bridge as bridge_module

    monkeypatch.setattr(bridge_module, "Bridge", FakeBridge)

    def _delete(session_id, agent_id):
        # web.input() reads the query string; the handler's DELETE passes
        # agent_id='' as the default, so the fake has to hand back the id the
        # test is deleting on behalf of.
        monkeypatch.setattr(
            sessions_api.web, "input", lambda **kwargs: {"agent_id": agent_id or ""}
        )
        return sessions_api.SessionDetailHandler().DELETE(session_id)

    return _delete


@pytest.fixture
def _tmp_workspace(tmp_path):
    return tmp_path


def _seed(project_store, session_prefs, session_id, agent_id, project):
    project_store.set_project_dir(session_id, project, agent_id=agent_id)
    session_prefs.set_prefs(session_id, agent_id=agent_id, model="claude-sonnet-5")


@pytest.mark.parametrize("agent_id", ["research", None])
def test_deleting_a_session_drops_that_agents_rows(
    stores, delete_session, tmp_path, agent_id
):
    project_store, session_prefs, rows = stores
    session_id = "sess-scoped"
    project = tmp_path / "proj"
    project.mkdir()
    _seed(project_store, session_prefs, session_id, agent_id, str(project))

    prefix = agent_id or "default"
    assert f"{prefix}::{session_id}" in rows(project_store)
    assert f"{prefix}::{session_id}" in rows(session_prefs)

    delete_session(session_id, agent_id)

    assert f"{prefix}::{session_id}" not in rows(project_store)
    assert f"{prefix}::{session_id}" not in rows(session_prefs)


def test_a_deleted_sessions_binding_is_not_readable_afterwards(
    stores, delete_session, tmp_path
):
    project_store, session_prefs, _rows = stores
    agent_id = "research"
    session_id = "sess-gone"
    project = tmp_path / "proj"
    project.mkdir()
    _seed(project_store, session_prefs, session_id, agent_id, str(project))

    delete_session(session_id, agent_id)

    # The two reads that Agent's next turn would do.
    assert project_store.get_project_dir(session_id, agent_id=agent_id) is None
    assert session_prefs.get_prefs(session_id, agent_id=agent_id) == {}


def test_deleting_one_agents_session_leaves_another_agents_alone(
    stores, delete_session, tmp_path
):
    """The namespacing is the reason agent_id has to be passed through."""
    project_store, session_prefs, rows = stores
    session_id = "sess-shared-id"
    for agent_id, folder in (("research", "p1"), ("writer", "p2")):
        project = tmp_path / folder
        project.mkdir()
        _seed(project_store, session_prefs, session_id, agent_id, str(project))

    assert sorted(rows(project_store)) == [
        f"research::{session_id}",
        f"writer::{session_id}",
    ]

    delete_session(session_id, "research")

    assert list(rows(project_store)) == [f"writer::{session_id}"]
    assert list(rows(session_prefs)) == [f"writer::{session_id}"]
    # And the surviving one is still fully readable.
    assert session_prefs.get_prefs(session_id, agent_id="writer") == {
        "model": "claude-sonnet-5"
    }


def test_deleting_a_session_with_nothing_bound_is_still_fine(stores, delete_session):
    project_store, session_prefs, rows = stores

    assert json.loads(delete_session("never-existed", "research"))["status"] == "success"
    assert rows(project_store) == {}
    assert rows(session_prefs) == {}


def test_a_failed_side_store_cleanup_does_not_fail_the_delete(
    stores, delete_session, tmp_path, monkeypatch
):
    """The cleanup is best-effort by design; the delete must still report success."""
    project_store, session_prefs, rows = stores
    session_id = "sess-resilient"
    project = tmp_path / "proj"
    project.mkdir()
    _seed(project_store, session_prefs, session_id, "research", str(project))

    import agent.workspace.session_prefs as prefs_module

    def boom(*_a, **_k):
        raise OSError("store is locked")

    monkeypatch.setattr(prefs_module, "forget_session", boom)

    assert json.loads(delete_session(session_id, "research"))["status"] == "success"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
