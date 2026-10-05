"""The settings API must not report a model pin the runtime ignores.

`AgentBridge.apply_session_prefs` drops the session override for a conversation
with members -- in a team every Agent answers on its own model, the owner
included -- while `_session_settings_state` reported `source="session"` for the
same conversation. The console reads that as a live pin
(`session-settings.js:221`), so the user is shown a check mark on a model
nothing answers with.

The contract these tests pin is agreement between the two, not a particular
resolution order.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.registry import AgentProfile, get_agent_registry
from channel.web.api.sessions import _session_settings_state


AGENT = "agent-writer"


def _runtime_override(prefs, owns_conversation=True):
    """agent_bridge.py:1373-1378, transcribed."""
    is_group = bool(prefs.get("members"))
    if owns_conversation and not is_group:
        return prefs.get("model")
    return None


class SessionModelSourceTest(unittest.TestCase):
    """Drives the real _session_settings_state against a stubbed config."""

    def setUp(self):
        # A real profile, because _session_settings_state also resolves the
        # owning Agent (for its own default and for the team section). conftest
        # resets the registry between tests.
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
        # members => the runtime passes set_session_override(None, None).
        state = self._state({
            "model": "claude-opus-5",
            "provider": "claudeAPI",
            "members": ["agent-writer", "agent-editor"],
        })

        self.assertNotEqual(
            state["model"]["source"], "session",
            "the console will show a check mark on a model no Agent answers with",
        )
        self.assertTrue(state["model"]["pin_ignored"])

    def test_the_reported_model_is_the_one_that_actually_answers(self):
        # The point of the fix: state.model has to name the model a request will
        # use, which is what the runtime resolves.
        for prefs in (
            {"model": "claude-opus-5", "provider": "claudeAPI"},
            {"model": "claude-opus-5", "provider": "claudeAPI", "members": ["a", "b"]},
        ):
            with self.subTest(members=bool(prefs.get("members"))):
                state = self._state(prefs, global_model="gpt-4o")
                applied = _runtime_override(prefs)
                reported = state["model"]["model"]

                if applied is None:
                    self.assertNotEqual(
                        reported, "claude-opus-5",
                        "reported the pinned model, but the runtime drops it",
                    )
                else:
                    self.assertEqual(reported, applied)

    def test_a_team_without_a_pin_is_untouched(self):
        state = self._state({"members": ["agent-writer"]}, global_model="gpt-4o")

        self.assertEqual(state["model"]["source"], "global")
        self.assertEqual(state["model"]["model"], "gpt-4o")

    def test_an_empty_member_list_is_not_a_team(self):
        # `members: []` is falsy, so the runtime treats it as a solo
        # conversation and the pin applies. The report has to agree.
        state = self._state({
            "model": "claude-opus-5", "provider": "claudeAPI", "members": [],
        })

        self.assertEqual(state["model"]["source"], "session")


if __name__ == "__main__":
    unittest.main()
