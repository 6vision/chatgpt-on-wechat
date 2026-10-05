"""A peer hand-off arriving over the transport must clear the local ACL.

``agent_delegate.py`` checks ``DelegationPolicy.allows()`` before it hands a
task to a teammate, but that check only ever runs in the process that *sends*
the hand-off. ``agent/multiagent/inbound.py::serve_invoke`` is the mirror of
that path on the receiving side, and it re-derived the trace, the depth and the
message-length limit from the policy — but never the allowlist. The payload's
``source_agent_id`` therefore only had to name *an* Agent to be believed.

The same function returns into ``_serve_clear`` before the policy is even read,
so a clear — which drops this Agent's transcript for a conversation — was
reachable from any source at all.

These tests pin the receiving side to the same policy the sending side applies.
"""

import pytest

from agent.registry import AgentProfile, AgentRegistry
from agent.multiagent.inbound import serve_invoke


def _registry():
    return AgentRegistry(
        [
            AgentProfile("local", "Local", "/tmp/inbound-local"),
            AgentProfile("teammate", "Teammate", "/tmp/inbound-teammate"),
            AgentProfile("stranger", "Stranger", "/tmp/inbound-stranger"),
        ],
        "local",
    )


class FakeBridge:
    """Answers every hand-off, so "did the turn run" is observable."""

    agent_registry = _registry()

    def __init__(self):
        self.contexts = []

    def agent_reply(self, query, context=None, on_event=None):
        self.contexts.append(context)
        from bridge.reply import Reply, ReplyType

        return Reply(ReplyType.TEXT, "answered")


def _payload(**overrides):
    payload = {
        "request_id": "req-1",
        "mode": "delegate",
        "source_agent_id": "teammate",
        "source_name": "Teammate",
        "target_agent_id": "local",
        "task": "read the config",
        "root_session_id": "root-1",
    }
    payload.update(overrides)
    return payload


def _serve(payload, policy):
    """Run one hand-off under *policy*; return (bridge, result chunks)."""
    import config as config_module

    bridge = FakeBridge()
    chunks = []
    original = config_module.conf
    config_module.conf = lambda: {"agent_delegation": policy}
    try:
        serve_invoke(payload, bridge, chunks.append)
    finally:
        config_module.conf = original
    return bridge, (chunks[-1] if chunks else {})


def _result(chunks):
    return chunks.get("status"), chunks.get("error") or ""


def test_allowlisted_source_is_served():
    bridge, chunks = _serve(
        _payload(), {"allowed_targets": {"teammate": ["local"]}}
    )

    assert len(bridge.contexts) == 1
    assert _result(chunks)[0] == "done"


def test_source_outside_the_allowlist_is_refused():
    # The ACL names only ``teammate``; a hand-off claiming to come from
    # ``stranger`` must be refused before any turn runs.
    bridge, chunks = _serve(
        _payload(source_agent_id="stranger", source_name="Stranger"),
        {"allowed_targets": {"teammate": ["local"]}},
    )

    assert bridge.contexts == []
    status, error = _result(chunks)
    assert status == "failed"
    assert "not allowed to delegate" in error


def test_source_absent_from_a_restricted_allowlist_is_refused():
    # An allowlist that does not mention the source at all is a closed door,
    # not an open one — same rule ``allows()`` applies on the sending side.
    bridge, chunks = _serve(
        _payload(source_agent_id="stranger", source_name="Stranger"),
        {"allowed_targets": {"teammate": ["local"]}},
    )

    assert bridge.contexts == []
    assert _result(chunks)[0] == "failed"


def test_an_agent_cannot_drive_itself_through_the_wire():
    # ``allows()`` refuses source == target even with no allowlist configured,
    # so a payload naming this Agent as its own caller is refused too.
    bridge, chunks = _serve(
        _payload(source_agent_id="local", source_name="Local"), {}
    )

    assert bridge.contexts == []
    status, error = _result(chunks)
    assert status == "failed"
    assert "not allowed" in error


def test_a_clear_is_refused_from_a_source_outside_the_allowlist(monkeypatch):
    """A clear drops this Agent's transcript, so the ACL must gate it too."""
    cleared = []

    class SessionService:
        def clear_context(self, session_id, agent_id=None, fanout=False):
            cleared.append((session_id, agent_id))

    import agent.chat.session_service as session_module

    monkeypatch.setattr(session_module, "SessionService", SessionService)

    _bridge, chunks = _serve(
        _payload(mode="clear", source_agent_id="stranger", source_name="Stranger"),
        {"allowed_targets": {"teammate": ["local"]}},
    )

    assert cleared == []
    status, error = _result(chunks)
    assert status == "failed"
    assert "not allowed" in error


def test_a_clear_from_an_allowlisted_source_still_works(monkeypatch):
    cleared = []

    class SessionService:
        def clear_context(self, session_id, agent_id=None, fanout=False):
            cleared.append((session_id, agent_id))

    import agent.chat.session_service as session_module

    monkeypatch.setattr(session_module, "SessionService", SessionService)

    _bridge, chunks = _serve(
        _payload(mode="clear"),
        {"allowed_targets": {"teammate": ["local"]}},
    )

    assert len(cleared) == 1
    assert cleared[0][1] == "local"
    assert _result(chunks)[0] == "done"


def test_the_refusal_names_both_agents():
    _bridge, chunks = _serve(
        _payload(source_agent_id="stranger", source_name="Stranger"),
        {"allowed_targets": {"teammate": ["local"]}},
    )

    _status, error = _result(chunks)
    assert "stranger" in error
    assert "local" in error


def test_a_disabled_policy_is_still_refused_before_the_acl():
    # ``enabled: false`` is the coarser switch; the ACL check must not turn a
    # disabled policy back into an allowed one.
    bridge, chunks = _serve(_payload(), {"enabled": False})

    assert bridge.contexts == []
    assert _result(chunks)[0] == "failed"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
