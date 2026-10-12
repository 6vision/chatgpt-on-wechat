"""A response_url push WeCom refused must leave the answer deliverable by poll,
while a push whose outcome is unknown keeps it claimed."""

import threading
import time

from channel.wecom_bot import wecom_bot_channel
from channel.wecom_bot.wecom_bot_channel import WecomBotChannel

STREAM_ID = "stream-1"
CONTENT = "Here is the picture."
RESPONSE_URL = "https://qyapi.weixin.qq.com/cgi-bin/aibot/respond?id=abc"


def _a_reply(status, body):
    """Stand-in for a ``requests`` response."""

    class _Response:
        status_code = status

        def json(self):
            return body

        @property
        def text(self):
            return str(body)

    return _Response()


def _channel(pushed=None):
    """A channel with a websocket send stub -- no socket, no thread, no config."""
    cls = WecomBotChannel.__wrapped__  # the class behind the @singleton wrapper
    channel = cls.__new__(cls)
    channel.mode = "websocket"
    channel._stream_states = {}
    channel._callback_streams = {}
    channel._callback_lock = threading.Lock()
    if pushed is not None:
        channel._send_via_response_url = lambda *a, **kw: pushed
    return channel


def _a_finished_stream(channel, content=CONTENT):
    """The state the streaming callbacks leave behind once a turn is done."""
    channel._callback_streams[STREAM_ID] = {
        "committed": content,
        "current": "",
        "finished": True,
        "images": [],
        "image_urls": [],
        "image_pending": False,
        "last_access": time.time(),
        "created_at": time.time(),
        "response_url": RESPONSE_URL,
        "delivered": False,
        "url_sent": False,
    }
    return channel._callback_streams[STREAM_ID]


def _run_the_fallback(channel, monkeypatch):
    """Drive the scheduled fallback inline and wait for its thread to finish."""
    created = []

    class _FakeThreading:
        Thread = staticmethod(lambda **kw: _remember(created, kw))

    def _remember(sink, kw):
        thread = threading.Thread(**kw)
        sink.append(thread)
        return thread

    monkeypatch.setattr(wecom_bot_channel, "threading", _FakeThreading)
    channel._schedule_response_url_fallback(STREAM_ID, delay=0)
    for thread in created:
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# What the push reports back.
# ---------------------------------------------------------------------------

def test_an_accepted_push_reports_success(monkeypatch):
    """errcode 0 with HTTP 200 is the only shape that counts as delivered."""
    channel = _channel()
    state = _a_finished_stream(channel)
    monkeypatch.setattr(
        wecom_bot_channel.requests,
        "post",
        lambda *a, **kw: _a_reply(200, {"errcode": 0, "errmsg": "ok"}),
    )

    _run_the_fallback(channel, monkeypatch)

    assert state["url_sent"] is True


def test_a_refused_push_reports_failure(monkeypatch):
    """HTTP 200 with a non-zero errcode is WeCom refusing the reply."""
    channel = _channel()
    state = _a_finished_stream(channel)
    monkeypatch.setattr(
        wecom_bot_channel.requests,
        "post",
        lambda *a, **kw: _a_reply(200, {"errcode": 40003, "errmsg": "invalid response_url"}),
    )

    _run_the_fallback(channel, monkeypatch)

    assert state["url_sent"] is False


def test_a_failed_status_reports_failure(monkeypatch):
    """A non-200 status is a failure too, however well-formed the body is."""
    channel = _channel()
    state = _a_finished_stream(channel)
    monkeypatch.setattr(
        wecom_bot_channel.requests, "post", lambda *a, **kw: _a_reply(500, {"errcode": 0})
    )

    _run_the_fallback(channel, monkeypatch)

    assert state["url_sent"] is False


# ---------------------------------------------------------------------------
# The consequence a poll sees.
# ---------------------------------------------------------------------------

def test_a_push_with_an_unknown_outcome_stays_claimed(monkeypatch):
    """A timeout may hide a delivered push, so a poll must not send it again."""
    channel = _channel()
    state = _a_finished_stream(channel)

    def timeout(*a, **kw):
        raise wecom_bot_channel.requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(wecom_bot_channel.requests, "post", timeout)

    _run_the_fallback(channel, monkeypatch)

    assert state["url_sent"] is True


def test_a_refused_push_lets_a_late_poll_hand_the_answer_over(monkeypatch):
    """`url_sent` is what the poll path reads to decide it has nothing left to
    say. A refused push must not pretend otherwise, or the answer is dropped."""
    channel = _channel()
    _a_finished_stream(channel)
    monkeypatch.setattr(channel, "_send_via_response_url", lambda *a, **kw: False)

    _run_the_fallback(channel, monkeypatch)

    packet = channel._callback_handle_stream_poll({"stream": {"id": STREAM_ID}})
    assert packet["stream"]["content"] == CONTENT
    assert packet["stream"]["finish"] is True


def test_an_accepted_push_keeps_a_late_poll_silent(monkeypatch):
    """The guard against a fix that "recovers" by always falling back to a poll:
    an accepted push must still finish silently rather than repeat the answer."""
    channel = _channel()
    _a_finished_stream(channel)
    monkeypatch.setattr(channel, "_send_via_response_url", lambda *a, **kw: True)

    _run_the_fallback(channel, monkeypatch)

    packet = channel._callback_handle_stream_poll({"stream": {"id": STREAM_ID}})
    assert packet["stream"]["content"] == ""
    assert packet["stream"]["finish"] is True
