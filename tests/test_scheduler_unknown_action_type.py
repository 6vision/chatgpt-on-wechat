"""An unknown ``action.type`` is recorded as a failed run, without a retry loop."""

import pytest

from agent.memory import clear_conversation_store_cache, get_conversation_store
from agent.registry import AgentProfile, AgentRegistry, set_agent_registry


@pytest.fixture
def one_agent(tmp_path):
    registry = AgentRegistry(
        [AgentProfile("default", "Default", str(tmp_path / "default"))],
        default_agent_id="default",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    try:
        yield registry
    finally:
        set_agent_registry(None)
        clear_conversation_store_cache()


def test_unknown_action_type_is_handled_but_recorded_as_error(monkeypatch, one_agent):
    from agent.tools.scheduler import integration

    monkeypatch.setattr(integration, "_is_channel_ready", lambda *a, **k: True)
    task = {
        "id": "task-42",
        "name": "Daily digest",
        "action": {"type": "remind_me", "channel_type": "feishu", "receiver": "u-1", "content": "hi"},
    }

    ok = integration._run_scheduled_task(task, agent_bridge=object(), agent_id="default")

    # Returning False would retry every tick and open another error run each time.
    assert ok is True
    runs = get_conversation_store().list_runs(task_source="scheduler")
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert runs[0]["error"] == "unknown action type: remind_me"
