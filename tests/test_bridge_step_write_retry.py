import sqlite3

from test_incremental_persist import (
    bridge_run as _bridge_fixture,
    _Script,
    _STEPS,
    _label,
)


bridge_run = _bridge_fixture


def test_bridge_retries_failed_step_in_actual_store(bridge_run, monkeypatch):
    store = bridge_run.store
    append = store.append_messages
    failed = False

    def fail_first_reply(session_id, messages, **kwargs):
        nonlocal failed
        if messages[0].get("role") == "assistant" and not failed:
            failed = True
            raise sqlite3.OperationalError("database is locked")
        return append(session_id, messages, **kwargs)

    monkeypatch.setattr(store, "append_messages", fail_first_reply)
    reply, rows = bridge_run(_Script(_STEPS))
    assert failed
    assert reply.type.name == "TEXT"
    assert [_label(message) for message in rows] == ["new q", "tool_use:t1", "tool_result:t1", "answer"]


def test_bridge_successful_writes_are_not_repeated(bridge_run):
    _, rows = bridge_run(_Script(_STEPS))
    assert [_label(message) for message in rows] == ["new q", "tool_use:t1", "tool_result:t1", "answer"]


def test_deleted_session_discard_does_not_request_retry(tmp_path):
    from agent.memory.conversation_store import ConversationStore
    from bridge.agent_bridge import AgentBridge

    store = ConversationStore(tmp_path / "conversations.db")
    bridge = object.__new__(AgentBridge)
    bridge.get_conversation_store = lambda agent_id=None: store
    result = bridge._persist_messages(
        "deleted",
        [{"role": "assistant", "content": "answer"}],
        create_if_missing=False,
    )
    assert result is True
    assert store.latest_seq("deleted") is None


def test_post_commit_index_failure_does_not_repeat_messages(bridge_run, monkeypatch):
    def failed_index(*args, **kwargs):
        raise OSError("artifact index unavailable")

    monkeypatch.setattr("agent.protocol.artifact.index_message_artifacts", failed_index)
    _, rows = bridge_run(_Script(_STEPS))
    assert [_label(message) for message in rows] == ["new q", "tool_use:t1", "tool_result:t1", "answer"]
