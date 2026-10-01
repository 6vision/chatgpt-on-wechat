# encoding:utf-8
"""
A cancelled worker is not a crashed worker.

ChatChannel._thread_pool_callback decides how a finished turn went by reading
worker.exception(). A Future that a /cancel cancelled raises
concurrent.futures.CancelledError from that call -- an Exception, but not the
asyncio.CancelledError the handler was catching, which has been a BaseException
since 3.8. Every deliberate cancel therefore fell through to the generic handler
and logged "Worker raise exception" with a traceback at ERROR: the one line an
operator reads after a cancel misbehaves, spent on the expected case.

Both halves are pinned here. A cancel stays INFO, and a genuine crash still
errors, so the fix cannot buy the first by swallowing the second.
"""
import asyncio
import logging
import os
import sys
import threading
from concurrent.futures import CancelledError, Future
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_channel(session_id="s1"):
    """A ChatChannel carrying only the state the done-callback touches.

    Built through __new__ so the real __init__ -- which starts a consume thread
    and reads config -- stays out of it, the way test_robustness_fixes.py does.
    """
    from channel.chat_channel import ChatChannel

    ch = ChatChannel.__new__(ChatChannel)
    ch.lock = threading.RLock()
    ch.sessions = {session_id: [MagicMock(), MagicMock()]}  # queue, semaphore
    ch.futures = {}
    return ch


@pytest.fixture
def captured(caplog):
    """caplog, wired to this module's logger.

    common/log.py builds the "log" logger with propagate off and its own console
    handler, so caplog's root handler never sees a record from it. Handing the
    capture handler to the logger directly is what makes the assertions below
    read anything at all.
    """
    log = logging.getLogger("log")
    previous_level = log.level
    log.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="log")
    try:
        yield caplog
    finally:
        log.removeHandler(caplog.handler)
        log.setLevel(previous_level)


def test_a_cancelled_future_raises_the_error_the_handler_has_to_catch():
    """The contract the fix rests on.

    Without this, the two tests below could pass while exercising nothing: if
    Future.exception() ever stopped raising on a cancelled Future, the callback
    would no longer reach either handler.
    """
    fut = Future()
    fut.cancel()

    with pytest.raises(CancelledError) as raised:
        fut.exception()

    # concurrent.futures', not asyncio's -- the latter is a BaseException since
    # 3.8, so an except clause naming it cannot catch this.
    assert not isinstance(raised.value, asyncio.CancelledError)
    assert isinstance(raised.value, Exception)


def test_a_cancelled_worker_is_info_and_not_an_error(captured):
    ch = _make_channel()
    fut = Future()
    fut.cancel()

    ch._thread_pool_callback("s1")(fut)

    info = [r.getMessage() for r in captured.records if r.levelno == logging.INFO]
    errors = [r.getMessage() for r in captured.records if r.levelno >= logging.ERROR]

    assert any("cancelled" in m for m in info), info
    assert not [m for m in errors if "raise exception" in m], errors
    # The session slot is handed back either way: a cancel must not strand it.
    ch.sessions["s1"][1].release.assert_called_once()


def test_a_crashed_worker_still_logs_at_error(captured):
    """A real failure has to stay loud, or the cancel fix swallowed it."""
    ch = _make_channel()
    fut = Future()
    fut.set_exception(RuntimeError("worker exploded"))

    ch._thread_pool_callback("s1")(fut)

    errors = [r.getMessage() for r in captured.records if r.levelno >= logging.ERROR]
    assert any("worker exploded" in m for m in errors), errors
    assert not [
        r.getMessage()
        for r in captured.records
        if r.levelno == logging.INFO and "cancelled" in r.getMessage()
    ]
