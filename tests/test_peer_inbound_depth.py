"""The delegation depth that gates a hand-off must come from the chain, not
from the payload.

``DelegationPolicy.max_depth`` is the bound on how many agents may sit between a
user's request and the Agent that answers it. On the sending side
(``agent_delegate.py``) the depth is *derived* — the caller reads the depth it
was itself handed and adds one — so it can only ever grow by the length of the
chain that actually arrived.

``agent/multiagent/inbound.py::serve_invoke`` reads the same field straight off
the wire instead::

    depth = int(payload.get("depth") or (len(trace) - 1))

The trace *is* the chain, and ``len(trace) - 1`` is the depth it implies, but a
non-empty ``depth`` in the payload wins over it and is never checked for
sanity. Two payload values defeat the guard outright:

- a **negative** depth clears the gate (``-100 > 3`` is False) and is then
  injected into the delegated context, so every later hop's ``+1`` stays
  negative and ``max_depth`` stops bounding the chain at all;
- an **understated** depth (``1`` on a four-hop chain) is taken at face value,
  and the receiving Agent stamps it into ``delegation_depth`` for the next hop
  to build on.

These tests pin the receiving side to the chain it can actually see.
"""

import pytest

from agent.registry import AgentProfile, AgentRegistry
from agent.multiagent.inbound import serve_invoke
from bridge.reply import Reply, ReplyType


def _registry():
    return AgentRegistry(
        [AgentProfile("local", "Local", "/tmp/depth-local")], "local"
    )


class FakeBridge:
    agent_registry = _registry()

    def __init__(self):
        self.depths = []

    def agent_reply(self, query, context=None, on_event=None):
        self.depths.append(context["delegation_depth"])
        return Reply(ReplyType.TEXT, "answered")


def _serve(payload, policy=None):
    import config as config_module

    bridge = FakeBridge()
    chunks = []
    original = config_module.conf
    config_module.conf = lambda: {"agent_delegation": policy if policy is not None else {}}
    try:
        serve_invoke(payload, bridge, chunks.append)
    finally:
        config_module.conf = original
    return bridge, (chunks[-1] if chunks else {})


def _payload(trace, **overrides):
    payload = {
        "request_id": "req-depth",
        "mode": "delegate",
        "source_agent_id": "peer",
        "source_name": "Peer",
        "target_agent_id": "local",
        "task": "do the thing",
        "trace": trace,
        "root_session_id": "root-depth",
    }
    payload.update(overrides)
    return payload


def test_depth_is_derived_from_the_chain_when_the_payload_omits_it():
    # peer -> a -> b -> local: three hops, so the depth is 3.
    bridge, chunks = _serve(
        _payload(["peer", "a", "b", "local"])
    )

    assert bridge.depths == [3]
    assert chunks.get("status") == "done"


def test_a_negative_depth_is_ignored_in_favour_of_the_chain():
    # -100 clears ``depth > max_depth`` outright, and once stamped into the
    # context every later hop's ``+1`` stays negative. The chain is what the
    # guard reads now, so the bogus value simply does not count.
    bridge, chunks = _serve(
        _payload(["peer", "a", "local"], depth=-100), {"max_depth": 3}
    )

    assert bridge.depths == [2]
    assert chunks.get("status") == "done"


def test_a_negative_depth_cannot_shrink_a_chain_that_is_already_too_deep():
    # Four hops claiming depth -100: the payload used to buy its way past
    # max_depth; the chain says 4 and max_depth says 3.
    bridge, chunks = _serve(
        _payload(["peer", "a", "b", "c", "local"], depth=-100), {"max_depth": 3}
    )

    assert bridge.depths == []
    assert chunks.get("status") == "failed"
    assert "exceeds" in (chunks.get("error") or "")


def test_an_understated_depth_cannot_shrink_the_chain():
    # A four-hop chain claiming depth 1 would leave the next hop counting from
    # 2, so the real chain would keep growing under the limit.
    bridge, chunks = _serve(
        _payload(["peer", "a", "b", "c", "local"], depth=1),
        {"max_depth": 3},
    )

    # Rejected outright: the payload claims 1, the chain says 4.
    assert bridge.depths == []
    assert chunks.get("status") == "failed"

    # And with no payload depth, the same chain is refused for exceeding 3.
    bridge2, chunks2 = _serve(
        _payload(["peer", "a", "b", "c", "local"]),
        {"max_depth": 3},
    )
    assert bridge2.depths == []
    assert chunks2.get("status") == "failed"


def test_an_overstated_depth_is_ignored_in_favour_of_the_chain():
    # The chain implies 1; a payload claiming 99 must not buy extra headroom,
    # nor push a legal hand-off over the limit on its own.
    bridge, chunks = _serve(
        _payload(["peer", "local"], depth=99), {"max_depth": 3}
    )

    assert bridge.depths == [1]
    assert chunks.get("status") == "done"

    # And a chain that really is too deep is still refused on its own merit.
    bridge2, chunks2 = _serve(
        _payload(["peer", "a", "b", "c", "local"], depth=0), {"max_depth": 3}
    )
    assert bridge2.depths == []
    assert "exceeds" in (chunks2.get("error") or "")


def test_a_chain_within_the_limit_is_served_with_its_real_depth():
    bridge, chunks = _serve(
        _payload(["peer", "a", "local"]), {"max_depth": 3}
    )

    assert bridge.depths == [2]
    assert chunks.get("status") == "done"


def test_a_non_numeric_depth_falls_back_to_the_chain():
    # Unparseable values have always fallen back to the chain length; that
    # behaviour is kept, it is only the *successful* parse that becomes trusted.
    bridge, chunks = _serve(
        _payload(["peer", "a", "local"], depth="deep")
    )

    assert bridge.depths == [2]
    assert chunks.get("status") == "done"


def test_the_injected_depth_is_never_below_zero():
    bridge, _chunks = _serve(
        _payload(["peer", "local"], depth=0)
    )

    # depth 0 is falsy, so it falls back to len(trace) - 1 == 1 for this hop.
    assert bridge.depths == [1]
    assert all(d >= 0 for d in bridge.depths)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
