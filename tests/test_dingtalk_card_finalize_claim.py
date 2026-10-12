"""The DingTalk card finalize must not claim delivery it did not achieve."""
import sys
import threading
import time
import types
from types import SimpleNamespace

import pytest


if "dingtalk_stream" not in sys.modules:
    _ds = types.ModuleType("dingtalk_stream")

    class _ChatbotMessage:
        pass

    class _AckMessage:
        STATUS_OK = 0
        STATUS_SYSTEM_EXCEPTION = 1

    class _ChatbotHandler:
        pass

    _ds.ChatbotMessage = _ChatbotMessage
    _ds.AckMessage = _AckMessage
    _ds.ChatbotHandler = _ChatbotHandler
    _ds.CallbackMessage = object
    sys.modules["dingtalk_stream"] = _ds

    _card_mod = types.ModuleType("dingtalk_stream.card_replier")

    class _CardReplier:
        def __init__(self, *args, **kwargs):
            pass

    class _AICardReplier(_CardReplier):
        pass

    class _AICardStatus:
        PROCESSING = 1
        INPUTING = 2
        FINISHED = 3
        FAILED = 5

    _card_mod.CardReplier = _CardReplier
    _card_mod.AICardReplier = _AICardReplier
    _card_mod.AICardStatus = _AICardStatus
    sys.modules["dingtalk_stream.card_replier"] = _card_mod


from bridge.context import Context, ContextType
from channel.dingtalk import dingtalk_stream_card as stream_card
from channel.dingtalk.dingtalk_stream_card import DingTalkCardStreamer


class _SlowCard:
    """A card whose final PUT blocks until the test releases it."""

    def __init__(self):
        self.card_instance_id = "card-1"
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = False

    def ai_streaming(self, markdown, append=False):
        self.calls.append(("stream", markdown))

    def streaming(self, card_instance_id, key, content, append, finished, failed):
        self.entered.set()
        self.release.wait(10)
        self.calls.append(("finalize", content))
        self.finished = True

    def ai_finish(self, markdown=None, button_list=None, tips=""):
        self.calls.append(("finish", markdown))

    def ai_fail(self):
        self.calls.append(("fail",))


class _FastCard(_SlowCard):
    """A card that finalizes without blocking."""

    def streaming(self, card_instance_id, key, content, append, finished, failed):
        self.entered.set()
        self.calls.append(("finalize", content))
        self.finished = True


def _context(**extra):
    incoming = SimpleNamespace(sender_staff_id="staff-1")
    msg = SimpleNamespace(
        is_group=False,
        incoming_message=incoming,
        robot_code="robot-1",
        sender_staff_id=incoming.sender_staff_id,
    )
    data = {"receiver": "staff-1", "isgroup": False, "msg": msg}
    data.update(extra)
    return Context(ContextType.TEXT, "hi", data)


def _streamer(card, context):
    return DingTalkCardStreamer(
        start_card=lambda: card,
        context=context,
        immediate=False,
        throttle_s=0,
    )


@pytest.fixture
def short_join(monkeypatch):
    """Shrink the finalize budget so the timeout path runs in milliseconds.

    raising=False: on unfixed code the constant does not exist yet, and the
    suite must still collect so the failure lands on behaviour.
    """
    monkeypatch.setattr(
        stream_card, "_FINALIZE_JOIN_SECONDS", 0.3, raising=False
    )


def test_a_stalled_finalize_leaves_the_reply_unclaimed(short_join):
    # RED: join() gives up while the final PUT is still in flight, so the
    # context must not say the stream delivered the reply -- otherwise
    # send() returns early and the webhook fallback never runs.
    card = _SlowCard()
    ctx = _context()
    streamer = _streamer(card, ctx)

    streamer.handle_event({"type": "message_update", "data": {"delta": "partial"}})
    # Only the streaming push has been queued; the finalize has not started.
    deadline = time.monotonic() + 5
    while not card.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert [call[0] for call in card.calls] == ["stream"]
    assert card.entered.is_set() is False

    start = time.monotonic()
    streamer.handle_event(
        {"type": "agent_end", "data": {"final_response": "the whole answer"}}
    )
    elapsed = time.monotonic() - start

    try:
        # The consequence first: this is what makes send() skip the fallback.
        assert ctx.get("dingtalk_streamed") is None
        assert card.entered.is_set(), "the finalize must actually be attempted"
        assert card.finished is False, "the finalize is still blocked"
        assert elapsed < 5, "agent_end must respect the join budget"
    finally:
        card.release.set()
        worker = streamer._worker
        if worker is not None:
            worker.join(timeout=5)


def test_a_delivered_finalize_still_claims_the_reply():
    # The success path is unchanged: a finalize that lands inside the budget
    # still marks the stream as delivered so send() does not double-reply.
    card = _FastCard()
    ctx = _context()
    streamer = _streamer(card, ctx)

    streamer.handle_event(
        {"type": "agent_end", "data": {"final_response": "the whole answer"}}
    )

    assert card.finished is True
    assert ("finish", "the whole answer") in card.calls
    assert ctx.get("dingtalk_streamed") is True


def test_a_failing_finalize_does_not_claim_the_reply():
    # An exception inside _apply already flips disabled via _disable(); the
    # delivery claim must follow it rather than override it.
    class _ExplodingCard(_FastCard):
        def streaming(self, *args, **kwargs):
            raise RuntimeError("Card.Streaming.Write is not available")

    card = _ExplodingCard()
    ctx = _context()
    streamer = _streamer(card, ctx)

    streamer.handle_event(
        {"type": "agent_end", "data": {"final_response": "the whole answer"}}
    )

    assert ctx.get("dingtalk_stream_failed") is True
    assert ctx.get("dingtalk_streamed") is None


def test_the_retired_worker_reference_is_released():
    # The sentinel ends the worker; the streamer must forget it so a later
    # event can start a fresh consumer instead of queueing into a dead one.
    card = _FastCard()
    ctx = _context()
    streamer = _streamer(card, ctx)

    streamer.handle_event(
        {"type": "agent_end", "data": {"final_response": "first answer"}}
    )
    assert streamer._worker is None

    before = len(card.calls)
    streamer._last_streamed = ""
    streamer.handle_event({"type": "message_update", "data": {"delta": "late"}})
    worker = streamer._worker
    if worker is not None:
        worker.join(timeout=5)

    assert any(call[0] == "stream" for call in card.calls[before:])
    assert streamer._queue.qsize() == 0


def test_the_join_budget_is_a_named_module_constant():
    # Pinned so a future edit cannot quietly reintroduce a bare literal and
    # lose the tests that depend on the timeout being tunable. Read through
    # the module so this test still collects against unfixed code.
    assert stream_card._FINALIZE_JOIN_SECONDS == 8.0
