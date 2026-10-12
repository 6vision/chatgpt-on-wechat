"""A transient SQLite write failure must not mark a streamed step persisted."""

from agent.chat.service import ChatService
from agent.memory.conversation_store import ConversationStore
from test_incremental_persist import _text, _tool_use, _tool_result

pytest_plugins = ("test_incremental_persist",)

_persist_messages = ChatService._persist_messages


def test_chat_stream_retries_failed_step_without_losing_its_tool_chain(
    chat_run, monkeypatch, tmp_path,
):
    store = ConversationStore(tmp_path / "history.db")
    monkeypatch.setattr("config.conf", lambda: {"conversation_persistence": True})
    monkeypatch.setattr("agent.memory.get_conversation_store", lambda *a, **k: store)
    monkeypatch.setattr(ChatService, "_persist_messages", staticmethod(_persist_messages))
    with store._connect() as conn:
        conn.executescript("""
            CREATE TRIGGER refuse_step BEFORE INSERT ON messages BEGIN
                SELECT RAISE(ABORT, 'temporary write refusal');
            END;
        """)

    class Run:
        def play(self, executor, query, on_event):
            executor.run_user_message = _text("user", query)
            executor.messages.append(executor.run_user_message)
            executor.messages.extend([_tool_use("read-1"), _tool_result("read-1")])
            on_event({"type": "turn_end", "data": {}})
            # Recover the real SQLite database before the next stream checkpoint.
            with store._connect() as conn:
                conn.execute("DROP TRIGGER refuse_step")
            executor.messages.append(_text("assistant", "answer"))
            on_event({"type": "turn_end", "data": {}})
            return "answer"

    chat_run.run(Run())
    messages = store.load_messages("s1", max_turns=100)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"][0]["text"] == "new q"
    assert messages[1]["content"][0]["id"] == "read-1"
    assert messages[2]["content"][0]["tool_use_id"] == "read-1"
    assert messages[3]["content"][0]["text"] == "answer"
