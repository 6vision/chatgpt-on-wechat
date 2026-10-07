"""The settings API reports the model a team conversation really answers with."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.registry import AgentProfile, get_agent_registry
from channel.web.api.sessions import _session_settings_state


AGENT = "agent-writer"


class SessionModelSourceTest(unittest.TestCase):
    def setUp(self):
        # _session_settings_state resolves the owning Agent's profile.
        self.root = tempfile.mkdtemp(prefix="session-source-")
        get_agent_registry().upsert(AgentProfile(
            id=AGENT, name="Writer", workspace=str(Path(self.root).resolve()),
        ))

    def _state(self, prefs, global_model="gpt-4o", global_bot_type="openai"):
        with patch("channel.web.api.sessions.conf", return_value={
            "model": global_model, "bot_type": global_bot_type,
        }), patch("agent.workspace.session_prefs.get_prefs", return_value=prefs), patch(
            "channel.web.api.sessions.permission_global_mode", return_value="full-access"
        ), patch(
            "channel.web.api.sessions._session_model_catalog", return_value=[]
        ):
            return _session_settings_state("s1", AGENT)

    def test_a_solo_pin_is_reported_as_a_pin(self):
        state = self._state({"model": "claude-opus-5", "provider": "claudeAPI"})

        self.assertEqual(state["model"]["source"], "session")
        self.assertEqual(state["model"]["model"], "claude-opus-5")

    def test_a_team_pin_is_not_reported_as_a_pin(self):
        state = self._state({
            "model": "claude-opus-5",
            "provider": "claudeAPI",
            "members": ["agent-writer", "agent-editor"],
        })

        self.assertEqual(state["model"]["source"], "global")
        self.assertEqual(state["model"]["model"], "gpt-4o")
        self.assertTrue(state["model"]["pin_ignored"])

    def test_a_team_without_a_pin_is_untouched(self):
        state = self._state({"members": ["agent-writer"]}, global_model="gpt-4o")

        self.assertEqual(state["model"]["source"], "global")
        self.assertEqual(state["model"]["model"], "gpt-4o")

    def test_an_empty_member_list_is_not_a_team(self):
        state = self._state({
            "model": "claude-opus-5", "provider": "claudeAPI", "members": [],
        })

        self.assertEqual(state["model"]["source"], "session")


if __name__ == "__main__":
    unittest.main()
