"""Secondary workspaces may have skipped releases before the global upgrade."""

import json
import sqlite3

import pytest

from agent.memory.conversation_store import (
    clear_conversation_store_cache,
    get_conversation_store,
    migrate_conversations_to_global,
)
from agent.registry import AgentProfile, AgentRegistry, set_agent_registry


@pytest.mark.parametrize("session_metadata", [False, True])
def test_secondary_history_without_later_optional_columns_survives_upgrade(
    tmp_path, session_metadata,
):
    secondary = tmp_path / "research"
    source = secondary / "memory" / "long-term" / "index.db"
    source.parent.mkdir(parents=True)
    with sqlite3.connect(source) as conn:
        # Pre-run-tracking / pre-pinning schema supported by _migrate().
        conn.executescript("""
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL, last_active INTEGER NOT NULL,
                msg_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL, seq INTEGER NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL,
                created_at INTEGER NOT NULL, UNIQUE(session_id, seq)
            );
        """)
        if session_metadata:
            for column, default in (
                ("channel_type", "TEXT NOT NULL DEFAULT ''"),
                ("title", "TEXT NOT NULL DEFAULT ''"),
                ("context_start_seq", "INTEGER NOT NULL DEFAULT 0"),
                ("pinned", "INTEGER NOT NULL DEFAULT 0"),
            ):
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} {default}")
        conn.execute(
            "INSERT INTO sessions(session_id, created_at, last_active, msg_count) "
            "VALUES ('history', 1, 2, 1)"
        )
        conn.execute(
            "INSERT INTO messages(session_id, seq, role, content, created_at) "
            "VALUES ('history', 0, 'user', ?, 1)",
            (json.dumps("irreplaceable question"),),
        )
    registry = AgentRegistry([
        AgentProfile("primary", "Primary", str(tmp_path / "primary")),
        AgentProfile("research", "Research", str(secondary)),
    ], default_agent_id="primary")
    set_agent_registry(registry)
    clear_conversation_store_cache()
    try:
        migrate_conversations_to_global(kickoff_async=False)
        store = get_conversation_store(str(secondary))
        assert [m["content"] for m in store.load_messages("history")] == ["irreplaceable question"]
        # A restart neither duplicates nor drops the imported history.
        clear_conversation_store_cache()
        migrate_conversations_to_global(kickoff_async=False)
        store = get_conversation_store(str(secondary))
        assert [m["content"] for m in store.load_messages("history")] == ["irreplaceable question"]
        with sqlite3.connect(source) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "messages" not in tables
            assert any(name.startswith("messages_migrated_") for name in tables)
    finally:
        set_agent_registry(None)
        clear_conversation_store_cache()
