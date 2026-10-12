"""Deleting an Agent must take its conversations with it."""

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def shared_store(monkeypatch):
    """Two Agents resolving to one shared index.db, plus their workspaces."""
    base = Path(tempfile.mkdtemp(prefix="agent-delete-conv-"))
    home = base / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    default_ws = base / "agents" / "default"
    alice_ws = base / "agents" / "alice"
    bob_ws = base / "agents" / "bob"
    for path in (default_ws, alice_ws, bob_ws):
        path.mkdir(parents=True)

    class _Profile:
        def __init__(self, agent_id, workspace):
            self.id = agent_id
            self.workspace = str(workspace)

    class _Registry:
        default_agent_id = "default"

        def list(self, include_disabled=True):
            return [
                _Profile("default", default_ws),
                _Profile("alice", alice_ws),
                _Profile("bob", bob_ws),
            ]

    import agent.registry as registry_module
    from agent.memory import conversation_store as cs

    monkeypatch.setattr(registry_module, "get_agent_registry", lambda: _Registry())
    monkeypatch.setattr(cs, "_store_instances", {})
    monkeypatch.setattr(cs, "_store_instance", None)

    db_path, alice_id = cs._resolve_global_binding(alice_ws)
    alice = cs.ConversationStore(db_path, alice_id)
    bob = cs.ConversationStore(db_path, "bob")

    yield {
        "base": base,
        "db_path": db_path,
        "alice_id": alice_id,
        "alice_ws": alice_ws,
        "bob_ws": bob_ws,
        "alice": alice,
        "bob": bob,
    }

    shutil.rmtree(base, ignore_errors=True)


def _rows(db_path, agent_id):
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE agent_id = ?", (agent_id,)
            ).fetchone()[0]
            for table in ("sessions", "messages", "runs", "artifacts")
        }
    finally:
        conn.close()


def _seed(shared, agent_id, session_id, marker):
    """Write one session, two messages, one artifact and one run."""
    store = shared[agent_id]
    store.append_messages(
        session_id=session_id,
        channel_type="web",
        messages=[
            {"role": "user", "content": f"{marker} question"},
            {"role": "assistant", "content": f"{marker} answer"},
        ],
    )
    store.record_artifacts(
        session_id, [{"path": str(shared["base"] / f"{marker}.txt"), "source": "manual"}]
    )
    store.create_run(
        f"run-{marker}", agent_id=store._agent_id, session_id=session_id,
        extras={"output": f"{marker} scheduled output"},
    )


def _sweep(agent_id):
    from agent.admin import _forget_agent_conversations

    return _forget_agent_conversations(agent_id)


# --- the sweep --------------------------------------------------------------


def test_the_sweep_removes_every_agent_scoped_row(shared_store):
    shared_store["bob"]._agent_id = shared_store["alice_id"]
    _seed(shared_store, "alice", "alice-session-1", "ALICE")
    assert _rows(shared_store["db_path"], shared_store["alice_id"]) == {
        "sessions": 1, "messages": 2, "runs": 1, "artifacts": 1,
    }

    removed = _sweep(shared_store["alice_id"])

    assert removed == 5
    assert _rows(shared_store["db_path"], shared_store["alice_id"]) == {
        "sessions": 0, "messages": 0, "runs": 0, "artifacts": 0,
    }


def test_the_sweep_leaves_other_agents_alone(shared_store):
    _seed(shared_store, "alice", "alice-session-1", "ALICE")
    bob = shared_store["bob"]
    bob.append_messages(
        session_id="bob-session",
        channel_type="web",
        messages=[{"role": "user", "content": "bob is fine"}],
    )

    _sweep(shared_store["alice_id"])

    assert bob.load_messages("bob-session")
    assert _rows(shared_store["db_path"], "bob")["messages"] == 1


def test_an_agent_with_nothing_stored_sweeps_clean(shared_store):
    assert _sweep(shared_store["alice_id"]) == 0


def test_an_empty_id_is_a_no_op(shared_store):
    # The default Agent binds to "", so "" must never reach a DELETE.
    assert _sweep("") == 0


# --- what deleting the workspace alone leaves behind ------------------------


def test_removing_the_workspace_does_not_reach_the_shared_file(shared_store):
    # This is the gap: the workspace is not where the conversations are.
    _seed(shared_store, "alice", "alice-session-1", "ALICE")
    db_path = shared_store["db_path"]

    shutil.rmtree(shared_store["alice_ws"], ignore_errors=True)

    assert db_path.exists()
    assert sum(_rows(db_path, shared_store["alice_id"]).values()) == 5


def test_recreating_the_same_id_would_inherit_the_transcript(shared_store):
    # The consequence, stated directly: same id, same handle, old history.
    from agent.memory import conversation_store as cs

    _seed(shared_store, "alice", "alice-session-1", "ALICE")
    shutil.rmtree(shared_store["alice_ws"], ignore_errors=True)

    reborn = cs.ConversationStore(
        shared_store["db_path"], shared_store["alice_id"]
    )
    assert [m.get("content") for m in reborn.load_messages("alice-session-1")] == [
        "ALICE question",
        "ALICE answer",
    ]

    _sweep(shared_store["alice_id"])

    reborn_after = cs.ConversationStore(
        shared_store["db_path"], shared_store["alice_id"]
    )
    assert reborn_after.load_messages("alice-session-1") == []


def test_the_sweep_survives_a_missing_table(shared_store):
    # runs/artifacts degrade to absent on older files; a sweep must not raise.
    conn = sqlite3.connect(str(shared_store["db_path"]))
    try:
        conn.execute("DROP TABLE runs")
        conn.commit()
    finally:
        conn.close()

    assert _sweep(shared_store["alice_id"]) == 0


# --- the whole delete_agent path --------------------------------------------


@pytest.fixture
def admin_service(shared_store, tmp_path, monkeypatch):
    """An AgentAdminService whose roster contains the two test Agents."""
    import agent.registry as registry_module
    from agent.admin import AgentAdminService

    base = shared_store["base"]
    instance_root = base / "instance"
    agents_root = instance_root / "agents"
    agents_root.mkdir(parents=True)
    for path in (shared_store["alice_ws"], shared_store["bob_ws"]):
        path.rename(agents_root / path.name)
    shared_store["alice_ws"] = agents_root / "alice"
    shared_store["bob_ws"] = agents_root / "bob"


    class _Registry:
        default_agent_id = "default"

        def __init__(self):
            self.default_agent_id = "default"
            self._profiles = {
                "default": registry_module.AgentProfile(
                    id="default", name="Default", workspace=str(instance_root),
                ),
                "alice": registry_module.AgentProfile(
                    id="alice", name="Alice", workspace=str(agents_root / "alice"),
                ),
                "bob": registry_module.AgentProfile(
                    id="bob", name="Bob", workspace=str(agents_root / "bob"),
                ),
            }

        def get(self, agent_id, require_enabled=True):
            from agent.admin import AgentAdminError

            profile = self._profiles.get(agent_id)
            if profile is None:
                raise AgentAdminError(f"unknown agent: {agent_id}")
            return profile

        def get_agent(self, agent_id, default=None):
            return self._profiles.get(agent_id, default)

        def __getitem__(self, agent_id):
            return self._profiles[agent_id]

        def __contains__(self, agent_id):
            return agent_id in self._profiles

        def __iter__(self):
            return iter(self._profiles.values())

        def list(self, include_disabled=True):
            return list(self._profiles.values())

        @property
        def revision(self):
            return "rev-test"

    monkeypatch.setattr(
        registry_module, "AgentRegistry", lambda *a, **k: _Registry(), raising=False
    )
    monkeypatch.setattr(AgentAdminService, "_registry", lambda self, s: _Registry())

    service = AgentAdminService(str(tmp_path / "config.json"), settings={})
    return service, shared_store


def test_delete_agent_leaves_no_transcript_behind(admin_service):
    service, shared = admin_service
    _seed(shared, "alice", "alice-session-1", "ALICE")
    assert sum(_rows(shared["db_path"], shared["alice_id"]).values()) == 5

    service.delete_agent("alice")

    assert sum(_rows(shared["db_path"], shared["alice_id"]).values()) == 0


def test_delete_agent_keeps_the_other_agents_transcripts(admin_service):
    service, shared = admin_service
    _seed(shared, "alice", "alice-session-1", "ALICE")
    shared["bob"].append_messages(
        session_id="bob-session", channel_type="web",
        messages=[{"role": "user", "content": "bob is fine"}],
    )

    service.delete_agent("alice")

    assert shared["bob"].load_messages("bob-session")
    assert shared["alice_ws"].exists()


def test_a_recreated_agent_starts_with_no_history(admin_service):
    service, shared = admin_service
    _seed(shared, "alice", "alice-session-1", "ALICE")

    service.delete_agent("alice")
    # Re-derive the handle the way a recreated Agent would: same id, same
    # shared file. The workspace is not what decides the binding.
    from agent.memory import conversation_store as cs

    reborn = cs.ConversationStore(shared["db_path"], shared["alice_id"])

    assert reborn.load_messages("alice-session-1") == []
    assert reborn.list_sessions()["total"] == 0
