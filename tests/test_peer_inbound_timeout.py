"""The relay wait on the receiving side is the local policy's, not the payload's.

``DelegationPolicy.from_config`` clamps ``timeout_seconds`` to
``[0.01, 600]`` and raises otherwise — a deliberate bound on how long a turn may
block. The sending side honours it by always passing the policy's own value
(``agent_delegate.py``: ``lock.acquire(timeout=policy.timeout_seconds)`` and
``timeout_seconds=policy.timeout_seconds`` on the wire).

``agent/multiagent/inbound.py`` reads the timeout off the payload instead::

    timeout = float(payload.get("timeout") or policy.timeout_seconds)
    ...
    lock.acquire(timeout=timeout)

So the clamp only ever applied to the value the *caller* chose; a hand-off that
named its own timeout got it verbatim. That timeout is what
``_relay_lock(session_id).acquire()`` blocks on, and holding that lock is what
serialises hands-off to one relay session — a request naming 100000 parks the
calling thread on the lock for close to a day, with the policy's ceiling never
consulted.

These tests pin the wait to the policy.
"""

import threading

import pytest

from agent.registry import AgentProfile, AgentRegistry
from agent.multiagent.inbound import serve_invoke
from bridge.reply import Reply, ReplyType


def _registry():
    return AgentRegistry(
        [AgentProfile("local", "Local", "/tmp/timeout-local")], "local"
    )


class FakeBridge:
    agent_registry = _registry()

    def agent_reply(self, query, context=None, on_event=None):
        return Reply(ReplyType.TEXT, "answered")


class _RecordingLock:
    """Stands in for the relay lock and remembers the timeout it was given."""

    def __init__(self):
        self.timeouts = []

    def acquire(self, timeout=None):
        self.timeouts.append(timeout)
        return False  # never actually block; the value is what matters

    def release(self):
        pass


@pytest.fixture
def recorded_lock(monkeypatch):
    lock = _RecordingLock()
    # ``_relay_lock`` is imported into serve_invoke's local scope, so the patch
    # has to land on the module it is imported from.
    import agent.tools.agent_delegate.agent_delegate as delegate_module

    monkeypatch.setattr(delegate_module, "_relay_lock", lambda session_id: lock)
    return lock


def _serve(payload, policy, lock):
    import config as config_module

    chunks = []
    original = config_module.conf
    config_module.conf = lambda: {"agent_delegation": policy}
    try:
        serve_invoke(payload, FakeBridge(), chunks.append)
    finally:
        config_module.conf = original
    return chunks[-1] if chunks else {}


def _payload(**overrides):
    payload = {
        "request_id": "req-timeout",
        "mode": "delegate",
        "source_agent_id": "peer",
        "source_name": "Peer",
        "target_agent_id": "local",
        "task": "do the thing",
        "root_session_id": "root-timeout",
    }
    payload.update(overrides)
    return payload


def test_a_payload_timeout_longer_than_the_policy_is_clamped(recorded_lock):
    _serve(_payload(timeout=100000.0), {"timeout_seconds": 0.05}, recorded_lock)

    assert recorded_lock.timeouts == [0.05]


def test_a_payload_timeout_far_past_the_ceiling_is_clamped(recorded_lock):
    _serve(_payload(timeout=10 ** 9), {}, recorded_lock)

    # The policy default is 600 and its hard ceiling is 600.
    assert recorded_lock.timeouts == [600.0]


def test_a_shorter_payload_timeout_still_applies(recorded_lock):
    # The caller may ask for less than the policy allows; that is not a bound
    # the receiver has to widen back.
    _serve(_payload(timeout=1.5), {"timeout_seconds": 30}, recorded_lock)

    assert recorded_lock.timeouts == [1.5]


def test_an_omitted_payload_timeout_uses_the_policy(recorded_lock):
    _serve(_payload(), {"timeout_seconds": 12.5}, recorded_lock)

    assert recorded_lock.timeouts == [12.5]


def test_a_non_numeric_payload_timeout_falls_back_to_the_policy(recorded_lock):
    result = _serve(_payload(timeout="soon"), {"timeout_seconds": 7}, recorded_lock)

    assert recorded_lock.timeouts == [7]
    assert result.get("status") == "failed"  # the lock was held; nothing ran


def test_a_zero_payload_timeout_is_not_treated_as_unset(recorded_lock):
    # ``0 or policy`` would silently become the policy value. A caller asking
    # for no wait at all should be told the target is busy, not waited on.
    _serve(_payload(timeout=0), {"timeout_seconds": 9}, recorded_lock)

    assert recorded_lock.timeouts == [0.0]


def test_a_negative_payload_timeout_is_clamped_to_zero(recorded_lock):
    _serve(_payload(timeout=-5.0), {"timeout_seconds": 3}, recorded_lock)

    # A negative wait is not a wait: it collapses to "do not wait at all",
    # which then reports the target as busy instead of parking the thread.
    assert recorded_lock.timeouts == [0.0]


def test_the_wait_never_exceeds_the_configured_policy_ceiling(recorded_lock):
    for claimed in (601.0, 3600.0, 100000.0, float("inf")):
        recorded_lock.timeouts.clear()
        _serve(_payload(timeout=claimed), {}, recorded_lock)
        assert recorded_lock.timeouts[0] <= 600.0, claimed


def test_a_refused_wait_reports_that_the_target_is_busy(recorded_lock):
    result = _serve(_payload(timeout=100000.0), {}, recorded_lock)

    assert result.get("status") == "failed"
    assert "timed out" in (result.get("error") or "")


def test_a_huge_claimed_wait_does_not_park_the_serving_thread(recorded_lock):
    """The point of the clamp: the wait ends when the policy says it does."""
    finished = threading.Event()

    def run():
        _serve(_payload(timeout=100000.0), {"timeout_seconds": 0.01}, recorded_lock)
        finished.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    assert finished.wait(timeout=5)
    assert recorded_lock.timeouts == [0.01]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
