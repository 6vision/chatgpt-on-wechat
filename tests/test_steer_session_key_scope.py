"""A steer reaches a non-default Agent's run, keyed by the scoped session id."""

import unittest
from unittest.mock import patch

from agent.protocol.steer import SteerRegistry, SteerStatus
from bridge.agent_bridge import AgentBridge


class _AgentEntry:
    def __init__(self, agent_id):
        self.id = agent_id
        self.name = agent_id


class _AgentRegistry:
    def __init__(self, default_agent_id="default"):
        self.default_agent_id = default_agent_id

    def get(self, agent_id=None, require_enabled=False):
        return _AgentEntry(agent_id or self.default_agent_id)

    def list(self):
        return [self.get(self.default_agent_id)]


def _bridge(default_agent_id="default"):
    bridge = AgentBridge.__new__(AgentBridge)
    bridge.agent_registry = _AgentRegistry(default_agent_id)
    return bridge


class SteerKeyScopeTest(unittest.TestCase):
    def test_the_default_agent_keeps_the_bare_key(self):
        bridge = _bridge()
        self.assertEqual(bridge.scoped_session_key("s1", None), "s1")
        self.assertEqual(bridge.scoped_session_key("s1", "default"), "s1")

    def test_agent_reply_scopes_the_steer_registration(self):
        bridge = _bridge()
        registry = SteerRegistry()
        seen = {}

        class _Agent:
            permission_mode = None
            tools = []
            captured_actions = []
            memory_manager = None
            skill_manager = None
            runtime_info = None
            workspace_dir = None
            max_steps = 8

            def run_stream(self, *args, **kwargs):
                seen["key"] = registry.submit(
                    bridge.scoped_session_key("s1", "agent-a"), "mid-run steer"
                ).status
                return "done"

        from bridge.context import Context

        context = Context()
        context["session_id"] = "s1"
        context["agent_id"] = "agent-a"

        with patch.object(AgentBridge, "_has_runtime", return_value=True), \
             patch.object(AgentBridge, "get_agent", return_value=_Agent()), \
             patch.object(AgentBridge, "route_context", return_value="agent-a"), \
             patch.object(AgentBridge, "_seed_team_members", return_value=None), \
             patch.object(AgentBridge, "_peer_speaker", return_value=None), \
             patch("bridge.agent_bridge.get_steer_registry", return_value=registry), \
             patch("bridge.agent_bridge.get_cancel_registry"), \
             patch("agent.evolution.trigger.mark_run_active", create=True):
            bridge.agent_reply("hello", context)

        self.assertEqual(seen.get("key"), SteerStatus.ACCEPTED)


if __name__ == "__main__":
    unittest.main()