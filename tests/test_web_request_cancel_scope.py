"""Exercise the production cancel endpoint with real in-process cancel events."""
import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.protocol.cancel import CancelTokenRegistry
from bridge.agent_bridge import AgentBridge


@pytest.mark.parametrize("agent_id", ["team-a", "default"])
def test_request_only_cancel_targets_the_resolved_agent(monkeypatch, agent_id):
    # Load the actual endpoint independently of unrelated optional web adapters.
    source = Path(__file__).parents[1] / "channel/web/core/channel.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "cancel_request"
    )
    registry = CancelTokenRegistry()
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: registry)
    bridge = SimpleNamespace(
        agent_registry=SimpleNamespace(default_agent_id="default"),
        agent_router=SimpleNamespace(resolve=lambda **kwargs: agent_id),
        _cancel_key=AgentBridge._cancel_key,
    )
    monkeypatch.setattr("bridge.bridge.Bridge", lambda: SimpleNamespace(get_agent_bridge=lambda: bridge))
    namespace = {
        "web": SimpleNamespace(data=lambda: json.dumps({"request_id": "r1", "agent_id": agent_id})),
        "json": json,
        "logger": logging.getLogger(__name__),
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    channel = SimpleNamespace(request_to_agent={}, sse_streams={})
    event = registry.register(AgentBridge._cancel_key(agent_id, "r1", "default"))
    other_event = registry.register(AgentBridge._cancel_key("team-b", "r1", "default"))
    default_event = registry.register("r1")
    result = json.loads(namespace["cancel_request"](channel))
    assert result == {"status": "success", "cancelled": 1}
    assert event.is_set()
    assert not other_event.is_set()
    if agent_id != "default":
        assert not default_event.is_set()
