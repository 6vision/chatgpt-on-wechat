"""The receiving side of a peer hand-off enforces its own delegation policy."""

import pytest

import config as config_module
from agent.multiagent.inbound import serve_invoke
from agent.registry import AgentProfile, AgentRegistry
from bridge.reply import Reply, ReplyType

ALLOW_PEER = {"allowed_targets": {"peer": ["local"]}}


class FakeBridge:
    agent_registry = AgentRegistry([AgentProfile("local", "Local", "/tmp/inbound-local")], "local")

    def __init__(self):
        self.depths = []

    def agent_reply(self, query, context=None, on_event=None):
        self.depths.append(context["delegation_depth"])
        return Reply(ReplyType.TEXT, "answered")


def _serve(monkeypatch, policy, **overrides):
    payload = {
        "request_id": "req-1",
        "mode": "delegate",
        "source_agent_id": "peer",
        "source_name": "Peer",
        "target_agent_id": "local",
        "task": "do the thing",
        "root_session_id": "root-1",
        **overrides,
    }
    monkeypatch.setattr(config_module, "conf", lambda: {"agent_delegation": policy})
    bridge, chunks = FakeBridge(), []
    serve_invoke(payload, bridge, chunks.append)
    return bridge, chunks[-1] if chunks else {}


@pytest.mark.parametrize("source, policy, served", [
    ("peer", ALLOW_PEER, True),
    ("stranger", ALLOW_PEER, False),
    ("local", {}, False),
    ("peer", {"enabled": False}, False),
])
def test_allowlist(monkeypatch, source, policy, served):
    bridge, result = _serve(monkeypatch, policy, source_agent_id=source)
    assert bool(bridge.depths) is served
    assert result.get("status") == ("done" if served else "failed")


@pytest.mark.parametrize("source, cleared", [("peer", True), ("stranger", False)])
def test_clear_is_gated_by_the_allowlist(monkeypatch, source, cleared):
    calls = []

    class SessionService:
        def clear_context(self, session_id, agent_id=None, fanout=False):
            calls.append(agent_id)

    import agent.chat.session_service as session_module

    monkeypatch.setattr(session_module, "SessionService", SessionService)
    _serve(monkeypatch, ALLOW_PEER, mode="clear", source_agent_id=source)
    assert calls == (["local"] if cleared else [])


@pytest.mark.parametrize("trace, depth, expected", [
    (["peer", "a", "b", "local"], None, 3),
    (["peer", "a", "local"], -100, 2),
    (["peer", "local"], 99, 1),
    (["peer", "a", "local"], "deep", 2),
    (["peer", "a", "b", "c", "local"], -100, None),
    (["peer", "a", "b", "c", "local"], 1, None),
])
def test_depth_comes_from_the_trace(monkeypatch, trace, depth, expected):
    extra = {} if depth is None else {"depth": depth}
    bridge, result = _serve(monkeypatch, {"max_depth": 3}, trace=trace, **extra)
    if expected is None:
        assert bridge.depths == [] and "exceeds" in result.get("error", "")
    else:
        assert bridge.depths == [expected]


class _RecordingLock:
    def __init__(self):
        self.timeouts = []

    def acquire(self, timeout=None):
        self.timeouts.append(timeout)
        return False

    def release(self):
        pass


@pytest.mark.parametrize("claimed, policy, expected", [
    (100000.0, {"timeout_seconds": 0.05}, 0.05),
    (10 ** 9, {}, 600.0),
    (float("inf"), {}, 600.0),
    (1.5, {"timeout_seconds": 30}, 1.5),
    (None, {"timeout_seconds": 12.5}, 12.5),
    ("soon", {"timeout_seconds": 7}, 7),
    (0, {"timeout_seconds": 9}, 0.0),
    (-5.0, {"timeout_seconds": 3}, 0.0),
])
def test_relay_wait_is_clamped_to_the_policy(monkeypatch, claimed, policy, expected):
    import agent.tools.agent_delegate.agent_delegate as delegate_module

    lock = _RecordingLock()
    monkeypatch.setattr(delegate_module, "_relay_lock", lambda session_id: lock)
    extra = {} if claimed is None else {"timeout": claimed}
    _bridge, result = _serve(monkeypatch, policy, **extra)
    assert lock.timeouts == [expected]
    assert "timed out" in result.get("error", "")
