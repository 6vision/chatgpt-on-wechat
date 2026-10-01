# encoding:utf-8
"""Cancelling a queued turn must not deadlock the channel's session lock.

``concurrent.futures.Future.cancel()`` runs the done-callbacks of a *PENDING*
future synchronously, on the thread that called it. ``consume()`` registers
``_thread_pool_callback()`` as that callback, and it takes ``self.lock`` to
release the session semaphore. ``cancel_session()`` / ``cancel_all_session()``
called ``future.cancel()`` while already holding the very same non-reentrant
``threading.Lock``, so the cancelling thread blocked forever while still holding
it -- wedging ``produce()`` and ``consume()`` for *every* session on the channel
until the process restarted. ``#reset`` and ``#resetall`` reach this whenever
more turns are queued than ``handler_pool`` has workers (8).

These tests build the future exactly the way ``consume()`` does -- a bare
``Future()`` in PENDING state with the real callback attached, since a future
with no callback never re-enters the lock -- and drive the cancel from a
separate thread, so a regression is a failed ``assert`` instead of a hung test
session. ``channel.lock`` is a real ``threading.Lock`` on purpose: the existing
cancel tests swap in an ``RLock``, which hides the reentrancy entirely.
"""

import threading
from concurrent.futures import Future
from types import SimpleNamespace

from bridge.agent_bridge import AgentBridge
from channel.chat_channel import ChatChannel
from common.dequeue import Dequeue

SESSION_ID = "s1"
OTHER_SESSION_ID = "s2"


class _StubAgentBridge:
    """Keys sessions the way AgentBridge does, without building a real runtime."""

    def __init__(self, default: str = "default"):
        self.agent_registry = SimpleNamespace(
            default_agent_id=default,
            get=lambda agent_id=None: SimpleNamespace(id=agent_id or default),
        )

    _cancel_key = staticmethod(AgentBridge._cancel_key)
    _resolve_agent_id = AgentBridge._resolve_agent_id
    scoped_session_key = AgentBridge.scoped_session_key


def _patch_bridge(monkeypatch):
    stub = _StubAgentBridge()
    monkeypatch.setattr(
        "bridge.bridge.Bridge", lambda: SimpleNamespace(get_agent_bridge=lambda: stub)
    )
    monkeypatch.setattr("channel.chat_channel.conf", lambda: {"concurrency_in_session": 1})


def _channel(session_ids=(SESSION_ID,)):
    """A channel with a real lock and one never-dispatched session per id.

    ``__new__`` skips ``__init__`` so the ``consume()`` thread is not started;
    only the attributes the cancel paths touch are populated.
    """
    channel = ChatChannel.__new__(ChatChannel)
    channel.lock = threading.Lock()
    channel.futures = {}
    channel.sessions = {
        session_id: [Dequeue(), threading.BoundedSemaphore(1)]
        for session_id in session_ids
    }
    return channel


def _queued_future(channel, session_id):
    """The future ``consume()`` would hold: PENDING, with the real callback."""
    future = Future()
    future.add_done_callback(channel._thread_pool_callback(session_id))
    return future


def _cancel_in_thread(func, *args, timeout=5):
    """Run a cancel path off the main thread; return (finished, error).

    The cancel must not run on the pytest main thread: a regression leaves that
    thread parked inside the channel lock forever, hanging the whole run instead
    of failing an assert. A raised exception is returned rather than swallowed,
    so a cancel that dies early cannot pass vacuously.
    """
    finished = threading.Event()
    box = {}

    def runner():
        try:
            func(*args)
        except BaseException as exc:  # noqa: BLE001 - reported by the caller
            box["error"] = exc
        finally:
            finished.set()

    threading.Thread(target=runner, daemon=True).start()
    return finished.wait(timeout), box.get("error")


def test_cancel_session_does_not_deadlock_the_channel_lock(monkeypatch):
    _patch_bridge(monkeypatch)
    channel = _channel((SESSION_ID, OTHER_SESSION_ID))
    channel.futures[SESSION_ID] = [_queued_future(channel, SESSION_ID)]

    finished, error = _cancel_in_thread(channel.cancel_session, SESSION_ID)

    assert finished, "cancel_session never returned: Future.cancel() deadlocked self.lock"
    assert error is None, f"cancel_session raised {error!r}"
    # The wedge was channel-wide, so the lock has to be free for every other
    # session once the cancel returns.
    assert channel.lock.acquire(timeout=5), "self.lock still held after cancel_session"
    channel.lock.release()


def test_cancel_all_session_does_not_deadlock_the_channel_lock(monkeypatch):
    _patch_bridge(monkeypatch)
    channel = _channel((SESSION_ID, OTHER_SESSION_ID))
    channel.futures[SESSION_ID] = [_queued_future(channel, SESSION_ID)]
    channel.futures[OTHER_SESSION_ID] = [_queued_future(channel, OTHER_SESSION_ID)]

    finished, error = _cancel_in_thread(channel.cancel_all_session)

    assert finished, "cancel_all_session never returned: Future.cancel() deadlocked self.lock"
    assert error is None, f"cancel_all_session raised {error!r}"
    assert channel.lock.acquire(timeout=5), "self.lock still held after cancel_all_session"
    channel.lock.release()


def test_cancel_session_releases_the_semaphore_of_the_cancelled_turn(monkeypatch):
    """The permit has to come back, or the session never dispatches again.

    ``consume()`` holds the session permit while a turn is in flight and
    ``_thread_pool_callback()`` gives it back. A fix that stopped the deadlock by
    skipping the callback would leave every cancelled session wedged instead.
    """
    _patch_bridge(monkeypatch)
    channel = _channel((SESSION_ID,))
    semaphore = channel.sessions[SESSION_ID][1]
    assert semaphore.acquire(blocking=False)  # consume() holds it while queued
    future = _queued_future(channel, SESSION_ID)
    channel.futures[SESSION_ID] = [future]

    finished, error = _cancel_in_thread(channel.cancel_session, SESSION_ID)

    assert finished, "cancel_session never returned: Future.cancel() deadlocked self.lock"
    assert error is None, f"cancel_session raised {error!r}"
    assert future.cancelled()
    assert semaphore.acquire(
        blocking=False
    ), "cancel_session left the session semaphore held, so the queue can never drain"
