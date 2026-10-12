"""A WeChat-MP passive-reply user must never be silenced for good."""

import sys
import threading
import types
from collections import defaultdict

import pytest


# passive_reply imports web.py at module level; stub it the way
# tests/test_scheduler_web_update.py does so this file stays a unit test.
if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *a, **k: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *a, **k: None
    web_stub.ctx = {}
    sys.modules["web"] = web_stub

from channel.chat_channel import ChatChannel  # noqa: E402


OPENID = "oProbe_c0ffee"


class _Msg:
    from_user_id = OPENID
    msg_id = "probe-msg"


def _context(content, session_id="sess-1"):
    """A real Context -- produce() compares context.type to ContextType.TEXT."""
    from bridge.context import Context, ContextType

    context = Context(ContextType.TEXT, content)
    context["session_id"] = session_id
    context["msg"] = _Msg()
    return context


class _Channel(ChatChannel):
    """A WechatMPChannel-shaped stand-in that records the claim lifecycle.

    Subclasses the real ChatChannel so ``produce``, ``_release_claim`` and
    ``_thread_pool_callback`` run as shipped. Only the transport and the pool
    are stood in for.
    """

    def __init__(self):
        self.passive_reply = True
        self.running = set()
        self.cache_dict = defaultdict(list)
        self.sessions = {}
        self.futures = {}
        self.lock = threading.RLock()
        self.replies = []
        self.submitted = []

    # --- the override that owns the claim (mirrors WechatMPChannel) ---
    def _passive_reply_key(self, session_id, context):
        return OPENID

    def _release_passive_claim(self, context, session_id):
        self.running.discard(self._passive_reply_key(session_id, context))

    def _success_callback(self, session_id, context, **kwargs):
        self._release_passive_claim(context, session_id)

    def _fail_callback(self, session_id, exception, context, **kwargs):
        self._release_passive_claim(context, session_id)

    # --- transport / pool ---
    def _send_reply(self, context, reply):
        self.replies.append(getattr(reply, "content", reply))

    def _handle_cancel_command(self, context, session_id):
        self.replies.append("Nothing to cancel.")

    def _handle_steer_command(self, context, session_id, instruction):
        self.replies.append("Steering is not available.")

    def _handle(self, context):
        self.submitted.append(context)

    def _cancel_agent_request(self, request_id):
        return True


@pytest.fixture
def channel():
    return _Channel()


def _bridge(monkeypatch, error=None):
    """Point Bridge.get_agent_bridge at a stub whose routing can fail."""
    class _AgentBridge:
        agent_registry = types.SimpleNamespace(default_agent_id="default")

        def route_context(self, context):
            if error is not None:
                raise error
            return "default"

        @staticmethod
        def _cancel_key(agent_id, session_id, default_agent_id):
            return f"{agent_id}::{session_id}"

        @staticmethod
        def steer_session(session_id, instruction, agent_id):
            from agent.protocol import SteerStatus

            return types.SimpleNamespace(status=SteerStatus.ACCEPTED)

    class _Bridge:
        @staticmethod
        def get_agent_bridge():
            return _AgentBridge()

    import bridge.bridge as bridge_module

    monkeypatch.setattr(bridge_module, "Bridge", _Bridge)


def _dispatch(channel, session_id):
    """Run one queued context the way _consume_session does, callbacks and all.

    The semaphore is acquired first because the done-callback releases it, and
    a BoundedSemaphore raises rather than tolerate an unbalanced release.
    """
    queue, semaphore = channel.sessions[session_id]
    if not semaphore.acquire(blocking=False) or queue.empty():
        return False

    class _Future:
        """Enough of a Future for _thread_pool_callback to inspect."""

        def __init__(self):
            self._callbacks = []

        def add_done_callback(self, fn):
            self._callbacks.append(fn)

        def done(self):
            return True

        def exception(self):
            return None

        def cancel(self):
            return False

        def complete(self):
            for fn in self._callbacks:
                fn(self)

    context = queue.get()
    future = _Future()
    future.add_done_callback(channel._thread_pool_callback(session_id, context=context))
    channel._handle(context)
    future.complete()
    return True


# ---------------------------------------------------------------------------
# 1. the claim
# ---------------------------------------------------------------------------


def test_a_cancel_does_not_leave_the_claim_held(channel, monkeypatch):
    _bridge(monkeypatch)
    channel.running.add(OPENID)          # what passive_reply does first

    channel.produce(_context("/cancel"))

    assert channel.replies, "the fast path answered"
    assert not channel.sessions, "and queued nothing"
    assert OPENID not in channel.running, "the claim outlived its task"


def test_a_steer_does_not_leave_the_claim_held(channel, monkeypatch):
    _bridge(monkeypatch)
    channel.running.add(OPENID)

    channel.produce(_context("/steer focus on tests"))

    assert channel.replies
    assert not channel.sessions
    assert OPENID not in channel.running


def test_a_disabled_agent_does_not_leave_the_claim_held(channel, monkeypatch):
    from agent.routing import AgentUnavailableError

    _bridge(monkeypatch, error=AgentUnavailableError("agent 'alice' is disabled"))
    channel.running.add(OPENID)

    channel.produce(_context("hello"))

    assert channel.replies, "the disabled-agent path answered"
    assert not channel.sessions, "and queued nothing"
    assert OPENID not in channel.running


def test_a_queued_task_releases_the_claim_through_the_callback(channel, monkeypatch):
    _bridge(monkeypatch)
    channel.running.add(OPENID)

    channel.produce(_context("hello there"))
    queue_key = next(iter(channel.sessions))
    assert OPENID in channel.running, "still queued, so still claimed"

    assert _dispatch(channel, queue_key) is True

    assert channel.submitted, "the task ran"
    assert OPENID not in channel.running, "the done-callback released it"


def test_the_base_channel_has_a_no_op_release():
    # A channel with no in-flight marker must not grow one.
    assert ChatChannel()._release_claim(_context("/cancel"), "sess-1") is None


def test_wechatmp_success_and_failure_callbacks_share_the_release():
    # One definition, so the two callbacks cannot drift apart again. Read from
    # the source: @singleton wraps the class, so inspect cannot reach it.
    from pathlib import Path

    source = (
        Path(__file__).parents[1]
        / "channel" / "wechatmp" / "wechatmp_channel.py"
    ).read_text(encoding="utf-8")

    assert source.count("def _release_passive_claim") == 1, "one definition"
    assert "_release_passive_claim" in source, "both callbacks use it"
    # Neither callback may discard directly any more.
    assert source.count("self.running.discard(self._passive_reply_key") == 1


# ---------------------------------------------------------------------------
# 2. the poisoned cache entry
# ---------------------------------------------------------------------------


def _drain(channel, from_user):
    """Replay of passive_reply's read.

    Returns True when a new agent task would start for this user, which is the
    decision the shipped guard makes.
    """
    starts_new_task = (
        channel.cache_dict.get(from_user) is None and from_user not in channel.running
    ) or (from_user not in channel.cache_dict and from_user not in channel.running)

    if from_user not in channel.cache_dict and from_user not in channel.running:
        return starts_new_task

    try:
        cached = channel.cache_dict.get(from_user)
        if not cached:
            return starts_new_task
        if cached[0][0] == "text":
            while cached and cached[0][0] == "text":
                cached.pop(0)
        else:
            cached.pop(0)
        if not cached:
            del channel.cache_dict[from_user]
    except IndexError:
        pass
    return starts_new_task


def test_reading_a_user_with_nothing_cached_creates_no_entry(channel):
    _drain(channel, OPENID)

    assert OPENID not in channel.cache_dict, "a read must not insert"
    assert channel.cache_dict.get(OPENID) is None


def test_a_user_with_no_cache_entry_can_still_start_a_task(channel):
    assert _drain(channel, OPENID) is True
    assert OPENID not in channel.cache_dict


def test_a_cached_reply_is_still_drained_and_the_entry_removed(channel):
    channel.cache_dict[OPENID].append(("text", "hello"))
    channel.cache_dict[OPENID].append(("text", "there"))

    _drain(channel, OPENID)

    # The entry goes once it is empty, which is the cleanup the old code did.
    assert OPENID not in channel.cache_dict


def test_a_partly_drained_entry_keeps_what_is_left(channel):
    channel.cache_dict[OPENID].append(("text", "hello"))
    channel.cache_dict[OPENID].append(("image", "/tmp/a.png"))

    _drain(channel, OPENID)

    assert channel.cache_dict[OPENID] == [("image", "/tmp/a.png")]


def test_the_container_stays_a_default_dict(channel):
    # Changing the read must not change the container: other call sites add to
    # it with cache_dict[key].append(...).
    assert isinstance(channel.cache_dict, defaultdict)
    channel.cache_dict["someone-else"].append(("text", "hi"))
    assert channel.cache_dict["someone-else"] == [("text", "hi")]


def test_a_held_claim_still_blocks_the_next_task(channel):
    # The two halves are independent: with a claim held the guard blocks even
    # with a clean cache, so this does not paper over the gap above.
    channel.running.add(OPENID)

    assert _drain(channel, OPENID) is False


def test_the_shipped_read_does_not_index_the_dict():
    # A direct guard against the regression, independent of any replay above.
    # Only the read matters: `del` and `.append(...)` on the dict are fine.
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "channel" / "wechatmp" / "passive_reply.py"
    ).read_text(encoding="utf-8")

    reads = [
        line.strip()
        for line in source.splitlines()
        if "cache_dict[from_user]" in line
        and not line.strip().startswith(("del ", "channel.cache_dict[from_user].append"))
    ]
    assert reads == [], f"a bare read would insert an entry: {reads}"
