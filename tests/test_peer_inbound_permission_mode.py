"""A hand-off across processes carries the caller's permission mode.

A delegated turn runs under a synthetic session id (``delegate_<src>_<tgt>_<hash>``)
that has no row in ``session_prefs``, so the session-scoped permission mode
cannot be looked up for it. A local hand-off therefore sets the mode on the
context it hands to ``agent_reply``::

    inherited_mode = self._inherited_permission_mode(source.id)
    if inherited_mode:
        delegated_context["delegated_permission_mode"] = inherited_mode

and ``agent_reply`` reads exactly that key::

    agent = self.get_agent(..., permission_mode=context.get("delegated_permission_mode"))

A hand-off to a teammate in *another* process has no such line. ``InvokeRequest``
has no field for it, the wire body omits it, and ``serve_invoke`` builds a
context without it — so the far side reads None, falls back to the global mode,
and a caller running read-only hands a teammate a full-access turn.

The three context keys the two paths build are otherwise identical: comparing
them leaves ``delegated_permission_mode`` as the only difference, and it is the
only one ``agent_reply`` reads.

These tests pin the value across the whole hop: request field, wire body, and
the context the far side ends up running.
"""

import pytest


def _request(**overrides):
    from agent.multiagent import InvokeRequest

    kwargs = {
        "request_id": "req-1",
        "target_id": "peer",
        "task": "read the config",
        "source_id": "local",
        "source_name": "Local",
        "root_session_id": "root-1",
        "trace": ("local", "peer"),
        "depth": 1,
    }
    kwargs.update(overrides)
    return InvokeRequest(**kwargs)


def test_the_request_carries_a_permission_mode():
    assert _request(permission_mode="read-only").permission_mode == "read-only"


def test_the_request_defaults_to_empty():
    """Empty means "the caller has no live instance"; the far side keeps its own."""
    assert _request().permission_mode == ""


def test_the_wire_body_carries_it():
    """cloud_client pulls in the socket stack, so read the body builder's source.

    What matters is that the mode reaches the wire under a key the receiving
    side reads, and that it is omitted rather than sent blank.
    """
    import pathlib
    import re

    source = pathlib.Path("common/cloud_client.py").read_text(encoding="utf-8")

    assert re.search(
        r'if request\.permission_mode:\s*\n\s+body\["permission_mode"\]'
        r" = request\.permission_mode",
        source,
    ), "the wire body never learns the caller's mode"


def test_an_empty_mode_is_left_off_the_wire():
    """Sending an empty field would have the far side treat '' as a mode."""
    import pathlib
    import re

    source = pathlib.Path("common/cloud_client.py").read_text(encoding="utf-8")
    guard = re.search(r"if request\.permission_mode:", source)

    assert guard, "an empty permission_mode would be sent as a blank field"


def test_the_sender_fills_the_request_field():
    """The whole hop only works if the sending side actually sets it."""
    import inspect
    from agent.tools.agent_delegate.agent_delegate import AgentDelegateTool

    source = inspect.getsource(AgentDelegateTool._delegate_peer)

    assert "permission_mode=self._inherited_permission_mode(" in source


def _serve(payload):
    """Run one inbound hand-off and return the context agent_reply received."""
    from agent.registry import AgentProfile, AgentRegistry
    from bridge.reply import Reply, ReplyType
    from agent.multiagent.inbound import serve_invoke
    import config as config_module

    registry = AgentRegistry(
        [
            AgentProfile("local", "Local", "/tmp/perm-local"),
            AgentProfile("peer", "Peer", "/tmp/perm-peer"),
        ],
        "local",
    )

    seen = {}

    class Bridge:
        agent_registry = registry

        def agent_reply(self, query, context=None, on_event=None):
            seen["context"] = context
            return Reply(ReplyType.TEXT, "ok")

    chunks = []
    original = config_module.conf
    config_module.conf = lambda: {"agent_delegation": {"allowed_targets": {"peer": ["local"]}}}
    try:
        serve_invoke(payload, Bridge(), chunks.append)
    finally:
        config_module.conf = original
    return seen.get("context"), (chunks[-1] if chunks else {})


def _payload(**overrides):
    payload = {
        "request_id": "req-1",
        "mode": "delegate",
        "source_agent_id": "peer",
        "source_name": "Peer",
        "target_agent_id": "local",
        "task": "read the config",
        "root_session_id": "root-1",
    }
    payload.update(overrides)
    return payload


def test_the_far_side_runs_under_the_caller_mode():
    context, chunks = _serve(_payload(permission_mode="read-only"))

    assert chunks.get("status") == "done"
    assert context["delegated_permission_mode"] == "read-only"


def test_a_payload_without_a_mode_leaves_the_far_side_alone():
    """No mode on the wire means no override, not an empty-string override."""
    context, _chunks = _serve(_payload())

    assert "delegated_permission_mode" not in context


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_mode_is_not_carried(blank):
    context, _chunks = _serve(_payload(permission_mode=blank))

    assert "delegated_permission_mode" not in context


def test_the_key_is_the_only_difference_between_the_two_contexts():
    """The local path is the reference; the wire path must match it."""
    import re
    import pathlib

    inbound = pathlib.Path("agent/multiagent/inbound.py").read_text(encoding="utf-8")
    delegate = pathlib.Path(
        "agent/tools/agent_delegate/agent_delegate.py"
    ).read_text(encoding="utf-8")

    wire_keys = set(re.findall(r'context\["(\w+)"\]\s*=', inbound))
    local_keys = set(re.findall(r'delegated_context\["(\w+)"\]\s*=', delegate))

    assert wire_keys == local_keys


def test_the_reading_side_is_the_one_that_asks_for_it():
    """Guard the contract: agent_reply must still read this key."""
    import inspect
    from bridge.agent_bridge import AgentBridge

    source = inspect.getsource(AgentBridge.agent_reply)

    assert 'context.get("delegated_permission_mode")' in source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
