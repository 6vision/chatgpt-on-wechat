"""A streaming OpenAI-compatible response must not park its consumer forever."""

import threading
import time
from unittest.mock import patch

import pytest

from channel.web.api import openai_compat as oc


COMPLETION_ID = "chatcmpl-idle"
SESSION_ID = "sess-idle"


@pytest.fixture
def short_idle(monkeypatch):
    """Shrink the idle budget so the timeout path runs in milliseconds.

    raising=False: on unfixed code the constant does not exist yet, and the
    suite must still collect so the failure lands on behaviour.
    """
    monkeypatch.setattr(oc, "_STREAM_IDLE_TIMEOUT_SECONDS", 0.3, raising=False)


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    from agent.protocol import CancelTokenRegistry

    # A released daemon worker can unregister after the next test starts.
    # Keep its cleanup scoped to the test that created it, even with reused IDs.
    instance = CancelTokenRegistry()
    monkeypatch.setattr("agent.protocol.get_cancel_registry", lambda: instance)
    yield instance
    instance.unregister(COMPLETION_ID)


def _stream(run_chat):
    """Drive _stream_completion with the cancel scope pinned to this test."""
    with patch.object(
        oc, "_request_cancel_scope", return_value=(COMPLETION_ID, SESSION_ID)
    ), patch("agent.protocol.get_cancel_registry", return_value=registry_of()):
        return oc._stream_completion(
            run_chat,
            query="hi",
            session_id=SESSION_ID,
            completion_id=COMPLETION_ID,
            created=0,
            model="m",
        )


def registry_of():
    from agent.protocol import get_cancel_registry

    return get_cancel_registry()


def _drain(frames, limit=200):
    return [frame for _, frame in zip(range(limit), frames)]


def test_a_stalled_stream_ends_instead_of_blocking(short_idle):
    # RED on unfixed code: the consumer stays parked on output.get() and the
    # generator never yields anything after the first content frame.
    released = threading.Event()

    def run_chat(query, session_id, send_chunk, **kwargs):
        send_chunk({"chunk_type": "content", "delta": "hello"})
        released.wait(10)  # the upstream never answers
        send_chunk({"chunk_type": "content", "delta": "world"})

    frames = _stream(run_chat)
    try:
        collected = []
        start = time.monotonic()
        for frame in frames:
            collected.append(frame)
        elapsed = time.monotonic() - start

        assert elapsed < 5, "the consumer must respect the idle budget"
        assert "data: [DONE]" in collected[-1]
        assert any('"error"' in frame for frame in collected)
    finally:
        released.set()


def test_a_stalled_stream_reports_an_error_before_ending(short_idle):
    released = threading.Event()

    def run_chat(query, session_id, send_chunk, **kwargs):
        send_chunk({"chunk_type": "content", "delta": "hello"})
        released.wait(10)

    frames = _stream(run_chat)
    try:
        collected = _drain(frames)
    finally:
        released.set()

    body = "".join(collected)
    assert "stopped producing events" in body
    assert '"finish_reason": "error"' in body.replace('": "', '": "')


def test_a_stalled_stream_still_cancels_the_run(short_idle, registry):
    # The point of the budget: release the worker that is holding the session
    # lock. completed stays False on this path so the finally block runs
    # _cancel_agent_request; a timeout that skipped it would leave the worker
    # parked in run_chat holding _SESSION_LOCKS[...] indefinitely.
    released = threading.Event()

    def run_chat(query, session_id, send_chunk, **kwargs):
        send_chunk({"chunk_type": "content", "delta": "hello"})
        released.wait(10)

    frames = _stream(run_chat)
    # Read the entry from this thread. _stream_completion registers and starts
    # the worker before it returns the generator, and run_chat stays parked in
    # released.wait(), so the entry is here deterministically -- reading it
    # from inside run_chat would race the worker reaching that line.
    cancel_event = registry.get_event(COMPLETION_ID)
    try:
        collected = _drain(frames)
    finally:
        released.set()
    body = "".join(collected)

    assert cancel_event is not None, "the run must be registered as cancellable"
    assert cancel_event.is_set(), "the stalled run must be cancelled"
    assert "data: [DONE]" in collected[-1]
    assert "stopped producing events" in body

    released.set()
    registry.unregister(COMPLETION_ID)


def test_a_healthy_stream_is_unaffected(short_idle):
    def run_chat(query, session_id, send_chunk, **kwargs):
        send_chunk({"chunk_type": "content", "delta": "hello"})
        send_chunk({"chunk_type": "content", "delta": " world"})

    collected = _drain(_stream(run_chat))
    body = "".join(collected)

    assert "data: [DONE]" in collected[-1]
    assert '"finish_reason": "stop"' in body
    assert "hello" in body and "world" in body
    assert "stopped producing events" not in body


def test_a_stream_slower_than_the_first_event_still_works(monkeypatch):
    # Only the *first* event has the tight 30s budget; a tool-heavy turn that
    # takes its time between chunks must not be cut off by the idle budget.
    monkeypatch.setattr(oc, "_STREAM_IDLE_TIMEOUT_SECONDS", 30, raising=False)

    def run_chat(query, session_id, send_chunk, **kwargs):
        send_chunk({"chunk_type": "content", "delta": "slow"})
        time.sleep(1.0)
        send_chunk({"chunk_type": "content", "delta": "but fine"})

    collected = _drain(_stream(run_chat))
    body = "".join(collected)

    assert "data: [DONE]" in collected[-1]
    assert "slow" in body and "but fine" in body
    assert "stopped producing events" not in body


def test_the_worker_error_path_still_surfaces(short_idle):
    # A worker that raises publishes _STREAM_ERROR, which the first-event check
    # turns into a 500 before any frame is yielded. That path must keep working
    # and must not be mistaken for an idle timeout.
    def run_chat(query, session_id, send_chunk, **kwargs):
        raise RuntimeError("upstream is down")

    with pytest.raises(oc.OpenAIAPIError) as caught:
        _stream(run_chat)

    assert caught.value.code == "internal_error"


def test_the_idle_budget_is_long_enough_for_a_slow_turn():
    # Pinned so a future edit cannot quietly shrink it to the first-event
    # budget and start killing legitimate long tool turns.
    assert oc._STREAM_IDLE_TIMEOUT_SECONDS >= 60
    assert oc._STREAM_IDLE_TIMEOUT_SECONDS > oc._FIRST_EVENT_TIMEOUT_SECONDS


def test_the_first_event_budget_is_untouched():
    assert oc._FIRST_EVENT_TIMEOUT_SECONDS == 30
