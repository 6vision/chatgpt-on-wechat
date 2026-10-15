# encoding:utf-8
"""The context-usage popover has to survive a restart.

The pie on the clear-context button is measured off the live Agent
(``Agent.get_context_usage``) and that Agent only exists while the process
does. After a restart ``peek_agent`` finds nothing for the session, so the
endpoint answered ``available: false`` and the popover came back empty -- even
though the session's history is still loaded into the next request, which is
exactly what the chart is there to show.

The numbers a run ended on are now stored with the session and served when
there is no live Agent to measure. Clearing the context drops the snapshot: it
describes a context that no longer exists, and a pie that stayed full after the
user emptied it would be worse than an empty one.
"""

import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    sys.modules["web"] = web_stub

from agent.memory.conversation_store import ConversationStore
from bridge.agent_bridge import AgentBridge
from channel.web.api import sessions as sessions_api


SESSION_ID = "session-usage"

# Shaped like Agent.get_context_usage(), so a payload that reaches the chart
# from the store is indistinguishable from a live one apart from `restored`.
USAGE = {
    "available": True,
    "estimated": False,
    "model": "gpt-4o",
    "window": 128000,
    "limit": 96000,
    "used": 41000,
    "messages": 12,
    "breakdown": {"system": 3000, "tools": 9000, "history": 29000, "free": 55000},
}


def _user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


class ContextUsageStoreTest(unittest.TestCase):
    """The snapshot itself: written with the session, dropped with its context."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ctx-usage-")
        self.db_path = Path(self.root) / "index.db"
        self.store = ConversationStore(self.db_path)

    def test_a_snapshot_round_trips(self):
        self.assertTrue(self.store.append_messages(SESSION_ID, [_user("hi")]))

        self.assertTrue(self.store.set_context_usage(SESSION_ID, USAGE))

        self.assertEqual(self.store.get_context_usage(SESSION_ID), USAGE)

    def test_a_session_that_was_never_persisted_is_not_written(self):
        self.assertFalse(self.store.set_context_usage(SESSION_ID, USAGE))
        self.assertIsNone(self.store.get_context_usage(SESSION_ID))

    def test_a_corrupt_payload_reads_as_no_snapshot(self):
        self.store.append_messages(SESSION_ID, [_user("hi")])
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute(
                "UPDATE sessions SET context_usage = ? WHERE session_id = ?",
                ("{not json", SESSION_ID),
            )
        conn.close()

        self.assertIsNone(self.store.get_context_usage(SESSION_ID))

    def test_clearing_the_context_drops_the_snapshot(self):
        self.store.append_messages(SESSION_ID, [_user("hi")])
        self.store.set_context_usage(SESSION_ID, USAGE)

        self.store.clear_context(SESSION_ID)

        self.assertIsNone(self.store.get_context_usage(SESSION_ID))

    def test_passing_none_drops_the_snapshot_too(self):
        self.store.append_messages(SESSION_ID, [_user("hi")])
        self.store.set_context_usage(SESSION_ID, USAGE)

        self.assertTrue(self.store.set_context_usage(SESSION_ID, None))

        self.assertIsNone(self.store.get_context_usage(SESSION_ID))

    def test_clearing_the_context_keeps_the_boundary_it_sets(self):
        self.store.append_messages(SESSION_ID, [_user("hi")])
        self.store.set_context_usage(SESSION_ID, USAGE)

        new_start = self.store.clear_context(SESSION_ID)

        self.assertEqual(self.store.get_context_start_seq(SESSION_ID), new_start)

    def test_a_snapshot_survives_a_later_store_instance(self):
        """The database file is the only thing a restart carries over."""
        self.store.append_messages(SESSION_ID, [_user("hi")])
        self.store.set_context_usage(SESSION_ID, USAGE)

        reopened = ConversationStore(self.db_path)

        self.assertEqual(reopened.get_context_usage(SESSION_ID), USAGE)

    def test_a_database_from_before_the_column_upgrades_in_place(self):
        """An existing install gains the column and keeps working."""
        self.store.append_messages(SESSION_ID, [_user("hi")])
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("ALTER TABLE sessions DROP COLUMN context_usage")
        conn.close()

        upgraded = ConversationStore(self.db_path)

        self.assertIsNone(upgraded.get_context_usage(SESSION_ID))
        self.assertTrue(upgraded.set_context_usage(SESSION_ID, USAGE))
        self.assertEqual(upgraded.get_context_usage(SESSION_ID), USAGE)


class ContextUsageSnapshotWriteTest(unittest.TestCase):
    """A finished run is what puts the numbers there in the first place."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ctx-usage-write-")
        self.store = ConversationStore(Path(self.root) / "index.db")
        self.store.append_messages(SESSION_ID, [_user("hi")])

    def _bridge(self, store_for=None):
        """Only get_conversation_store is used, so the rest stays unbuilt."""
        bridge = AgentBridge.__new__(AgentBridge)
        bridge.get_conversation_store = store_for or (lambda agent_id=None: self.store)
        return bridge

    def test_the_run_s_numbers_are_stored_against_the_owner(self):
        agent = types.SimpleNamespace(get_context_usage=lambda: USAGE)
        asked = []

        def _store_for(agent_id=None):
            asked.append(agent_id)
            return self.store

        self._bridge(_store_for).remember_context_usage(agent, SESSION_ID, "writer")

        self.assertEqual(asked, ["writer"])
        self.assertEqual(self.store.get_context_usage(SESSION_ID), USAGE)

    def test_a_session_less_turn_stores_nothing(self):
        agent = types.SimpleNamespace(get_context_usage=lambda: USAGE)

        self._bridge().remember_context_usage(agent, None, "writer")

        self.assertIsNone(self.store.get_context_usage(SESSION_ID))

    def test_a_failing_snapshot_does_not_escape(self):
        def _boom():
            raise RuntimeError("no usage available")

        agent = types.SimpleNamespace(get_context_usage=_boom)

        self._bridge().remember_context_usage(agent, SESSION_ID, "writer")

        self.assertIsNone(self.store.get_context_usage(SESSION_ID))

    def test_an_unresolvable_agent_does_not_escape(self):
        agent = types.SimpleNamespace(get_context_usage=lambda: USAGE)

        def _boom(agent_id=None):
            raise KeyError(agent_id)

        self._bridge(_boom).remember_context_usage(agent, SESSION_ID, "ghost")

        self.assertIsNone(self.store.get_context_usage(SESSION_ID))


class _NoAgentBridge:
    """A bridge whose sessions have no live Agent — the post-restart state."""

    def get_agent_bridge(self):
        return types.SimpleNamespace(peek_agent=lambda session_id, agent_id=None: None)


class _LiveAgentBridge:
    def __init__(self, agent):
        self.agent = agent

    def get_agent_bridge(self):
        return types.SimpleNamespace(
            peek_agent=lambda session_id, agent_id=None: self.agent
        )


class ContextUsageEndpointTest(unittest.TestCase):
    """What the popover is served: live numbers, else the last run's."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ctx-usage-api-")
        self.store = ConversationStore(Path(self.root) / "index.db")
        self.store.append_messages(SESSION_ID, [_user("hi")])

    def _get(self, bridge):
        with patch.object(sessions_api, "_require_auth"), patch.object(
            sessions_api.web, "header", lambda *a, **k: None
        ), patch.object(
            sessions_api.web, "ctx", types.SimpleNamespace(env={})
        ), patch(
            # The handler imports it inside GET, so the patch goes on the source.
            "bridge.bridge.Bridge", lambda: bridge
        ), patch(
            "agent.memory.get_conversation_store", lambda *a, **k: self.store
        ):
            return json.loads(sessions_api.SessionContextUsageHandler().GET(SESSION_ID))

    def test_an_empty_session_still_reads_as_unavailable(self):
        payload = self._get(_NoAgentBridge())

        self.assertEqual(payload, {"status": "success", "available": False})

    def test_the_last_run_s_numbers_are_served_after_a_restart(self):
        self.store.set_context_usage(SESSION_ID, USAGE)

        payload = self._get(_NoAgentBridge())

        self.assertEqual(payload["status"], "success")
        self.assertTrue(payload["available"])
        self.assertTrue(payload["restored"])
        self.assertEqual(payload["breakdown"], USAGE["breakdown"])
        self.assertEqual(payload["used"], USAGE["used"])

    def test_a_live_agent_is_measured_rather_than_restored(self):
        live = dict(USAGE, used=12000)
        self.store.set_context_usage(SESSION_ID, USAGE)

        payload = self._get(_LiveAgentBridge(types.SimpleNamespace(
            get_context_usage=lambda: dict(live)
        )))

        self.assertEqual(payload["used"], 12000)
        self.assertNotIn("restored", payload)

    def test_clearing_the_context_leaves_nothing_to_restore(self):
        self.store.set_context_usage(SESSION_ID, USAGE)

        self.store.clear_context(SESSION_ID)

        self.assertEqual(self._get(_NoAgentBridge()), {"status": "success", "available": False})


if __name__ == "__main__":
    unittest.main()
