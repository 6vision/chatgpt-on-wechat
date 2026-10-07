"""The reserved ``default`` alias is this Agent, not another one.

``AgentRegistry.get_addressed`` treats the bare id ``"default"`` as the default
Agent whatever it was really given, and ``CloudClient._alias_agent_id`` reports
the default Agent to remote callers under exactly that id. So a delegation chain
that already ran here comes back naming that Agent as ``"default"``.

``serve_invoke`` folds the aliases the caller supplied onto the local id before
it compares the chain:

    aliases = {addressed_id, *(str(a).strip() for a in payload.get("target_aliases") or [])}

but ``addressed_id`` is only the id this request happened to be addressed by. When
the target is named by its real id, the reserved alias is not in that set, and
``"default"`` survives into the trace as if it were somebody else. The chain
then holds two entries for one Agent, and the cycle guard is comparing strings:

    # a chain that has already run on the default Agent, named by its real id
    trace = ["main-agent"]                        -> served
    # the same chain, with that one hop named by the reserved alias
    trace = ["main-agent", "default"]             -> "Delegation cycle rejected"

The rejection is right for the wrong reason, and the first case is the bug: the
default Agent hands off to itself, one alias deeper, and ``max_depth`` is spent
on a hop that never went anywhere.

These tests pin the alias to the local id wherever the target is the default
Agent, and leave the single-Agent install alone.
"""

import pytest


@pytest.fixture
def registry():
    """A two-Agent roster whose default has a real id, not ``default``."""
    from agent.registry import AgentProfile, AgentRegistry

    return AgentRegistry(
        [
            AgentProfile("main-agent", "Main", "/tmp/alias-w1"),
            AgentProfile("helper", "Helper", "/tmp/alias-w2"),
        ],
        "main-agent",
    )


def _serve(payload, registry):
    from bridge.reply import Reply, ReplyType
    from agent.multiagent.inbound import serve_invoke
    import config as config_module

    seen = {}

    class Bridge:
        agent_registry = registry

        def agent_reply(self, query, context=None, on_event=None):
            seen["context"] = context
            return Reply(ReplyType.TEXT, "ok")

    chunks = []
    original = config_module.conf
    config_module.conf = lambda: {"agent_delegation": {}}
    try:
        serve_invoke(payload, Bridge(), chunks.append)
    finally:
        config_module.conf = original
    return seen.get("context"), (chunks[-1] if chunks else {})


def _payload(trace, addressed, **overrides):
    payload = {
        "request_id": "req-1",
        "mode": "delegate",
        "source_agent_id": "helper",
        "source_name": "Helper",
        "target_agent_id": addressed,
        "task": "read the config",
        "root_session_id": "root-1",
        "trace": trace,
    }
    payload.update(overrides)
    return payload


def test_a_chain_naming_the_default_agent_by_its_alias_is_rejected(registry):
    """The Agent already ran once; coming back under another name is still a cycle."""
    _context, chunks = _serve(
        _payload(["helper", "main-agent", "default"], "main-agent"), registry
    )

    assert chunks.get("status") == "failed"
    assert "cycle rejected" in (chunks.get("error") or "")


def test_the_same_chain_by_real_id_is_also_rejected(registry):
    """Both spellings must reach the same verdict."""
    _context, chunks = _serve(
        _payload(["main-agent", "helper", "main-agent"], "main-agent"), registry
    )

    assert chunks.get("status") == "failed"
    assert "cycle rejected" in (chunks.get("error") or "")


def test_a_fresh_chain_still_runs(registry):
    context, chunks = _serve(_payload(["helper"], "main-agent"), registry)

    assert chunks.get("status") == "done"
    assert context["delegation_trace"] == ["helper", "main-agent"]


def test_a_chain_that_only_mentions_the_alias_itself_is_fine(registry):
    """Addressing by the alias is the normal path for a remote caller."""
    context, chunks = _serve(_payload(["helper", "default"], "default"), registry)

    assert chunks.get("status") == "done"
    assert context["delegation_trace"] == ["helper", "main-agent"]


def test_the_alias_is_folded_wherever_it_appears(registry):
    """Not just at the tail — a hop in the middle names the same Agent too.

    Folding it there is what makes the cycle guard see one Agent rather than
    two: ``default -> helper -> default`` is a chain that already came back here.
    """
    _context, chunks = _serve(
        _payload(["default", "helper"], "main-agent"), registry
    )

    assert chunks.get("status") == "failed"
    assert "cycle rejected" in (chunks.get("error") or "")
    # The refusal names the folded chain, so the log shows one Agent, not two.
    assert "default" not in (chunks.get("error") or "")


def test_the_roster_drops_the_alias_too(registry):
    """Members are folded by the same helper, so the ghost cannot reappear there."""
    context, _chunks = _serve(
        _payload(["helper"], "main-agent", members=["default", "helper"]), registry
    )

    assert "default" not in context["delegation_members"]


def test_a_non_default_target_leaves_the_alias_alone(registry):
    """``default`` is only this Agent's alias when it IS the default Agent.

    With ``helper`` as the default, a chain naming ``default`` means helper, so
    folding it onto ``main-agent`` would be wrong in the other direction.
    """
    from agent.registry import AgentProfile, AgentRegistry

    roster = AgentRegistry(
        [
            AgentProfile("main-agent", "Main", "/tmp/alias-w1"),
            AgentProfile("helper", "Helper", "/tmp/alias-w2"),
        ],
        "helper",  # helper is the default now
    )
    context, chunks = _serve(
        _payload(["main-agent", "helper"], "main-agent"), roster
    )

    assert chunks.get("status") == "failed"  # helper already ran, by real id
    assert "cycle rejected" in (chunks.get("error") or "")


def test_a_single_agent_install_is_unaffected():
    """When the real id already *is* ``default`` there is nothing to fold."""
    from agent.registry import AgentProfile, AgentRegistry

    roster = AgentRegistry([AgentProfile("default", "Solo", "/tmp/alias-solo")], "default")
    context, chunks = _serve(_payload(["helper"], "default"), roster)

    assert chunks.get("status") == "done"
    assert context["delegation_trace"] == ["helper", "default"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
