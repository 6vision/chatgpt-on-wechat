"""The shared consume loop must survive one bad session.

``ChatChannel.consume`` is the message pump every channel subclass starts in
``__init__``, and its ``while True`` body is bare: any exception raised while
looking at a session unwinds out of the loop and kills the pump for the rest of
the process lifetime. Messages then pile up in the per-session queues and the
bot goes silent, while the process itself stays up and nothing in the log names
the cause.

Two ways to raise in there today:

* the ``assert len(self.futures[session_id]) == 0`` guard -- an ``assert`` used
  for a runtime check, which also vanishes under ``python -O``;
* ``self.futures[session_id]`` is only created once a context is submitted, so
  an empty session whose semaphore looks drained raises ``KeyError`` first.
"""

import queue
import threading
import time
from unittest.mock import patch

from channel.chat_channel import ChatChannel

import channel.chat_channel as chat_mod


class _Stop(Exception):
    """Raised from the patched ``time.sleep`` to end the consume loop."""


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        threading.Event().wait(0.02)
    return False


def _channel():
    """A ChatChannel with its __init__ skipped (that would start the pump)."""
    channel = ChatChannel.__new__(ChatChannel)
    channel.futures = {}
    channel.sessions = {}
    channel.lock = threading.Lock()
    return channel


def _run_consume(channel, sleeps):
    """Drive consume() on a thread; stop it once it has slept twice."""

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise _Stop

    real_sleep = time.sleep
    time.sleep = fake_sleep
    try:
        threading.Thread(target=channel.consume, daemon=True).start()
        return _wait_for(lambda: len(sleeps) >= 2)
    finally:
        time.sleep = real_sleep


def test_empty_session_without_futures_does_not_kill_the_loop(monkeypatch):
    """A session that was never submitted reaches the assert/KeyError path.

    ``futures`` has no entry for it, so ``self.futures[session_id]`` raises
    before the assert does. The pump has to log it and go round again.
    """
    sleeps = []
    channel = _channel()
    channel.sessions["never-submitted"] = [queue.Queue(), threading.Semaphore(1)]

    assert _run_consume(channel, sleeps), (
        "the consume loop stopped on a session it could not drain; every "
        "session queued after this point is never handled"
    )


def test_failed_submit_does_not_kill_the_loop(monkeypatch):
    """A rejected executor submission must not end the pump either."""
    sleeps = []
    channel = _channel()
    pending = queue.Queue()
    pending.put({"context": "payload"})
    channel.sessions["busy"] = [pending, threading.Semaphore(1)]

    with patch.object(
        chat_mod.handler_pool, "submit", side_effect=RuntimeError("pool is shutting down")
    ):
        assert _run_consume(channel, sleeps), (
            "the consume loop stopped after a failed handler_pool.submit"
        )


def test_a_healthy_session_is_still_dispatched():
    """The happy path is unchanged: a queued context reaches the executor."""
    channel = _channel()
    pending = queue.Queue()
    context = {"context": "payload"}
    pending.put(context)
    channel.sessions["ok"] = [pending, threading.Semaphore(1)]

    with patch.object(chat_mod.handler_pool, "submit") as submit:
        channel._consume_session("ok")

    assert submit.call_args[0][1] is context
    assert channel.sessions["ok"][0].empty()
