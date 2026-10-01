"""QQ msg_seq counters must keep counting per message, and must not pile up
for every message the bot has ever answered."""

from datetime import datetime, timedelta

from channel.qq import qq_channel
from common import expired_dict


def _make_channel():
    """A bare channel holding only what ``_get_next_msg_seq`` touches."""
    # @singleton hands back a factory function; the class sits on __wrapped__.
    cls = qq_channel.QQChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._msg_seq_counter = expired_dict.ExpiredDict(qq_channel._MSG_SEQ_TTL_SECONDS)
    return ch


def test_replies_to_one_message_keep_counting_up():
    ch = _make_channel()

    assert ch._get_next_msg_seq("msg-1") == 1
    assert ch._get_next_msg_seq("msg-1") == 2
    assert ch._get_next_msg_seq("msg-1") == 3


def test_each_message_starts_at_one():
    ch = _make_channel()

    assert ch._get_next_msg_seq("msg-1") == 1
    assert ch._get_next_msg_seq("msg-2") == 1


def test_a_reply_interleaved_with_new_messages_keeps_counting():
    ch = _make_channel()

    assert ch._get_next_msg_seq("msg-1") == 1
    for i in range(5):
        ch._get_next_msg_seq(f"other-{i}")
    assert ch._get_next_msg_seq("msg-1") == 2


def test_counters_past_the_reply_window_are_dropped(monkeypatch):
    now = [datetime(2026, 1, 1, 12, 0, 0)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0]

    monkeypatch.setattr(expired_dict, "datetime", Clock)
    ch = _make_channel()
    for i in range(1000):
        ch._get_next_msg_seq(f"msg-{i}")

    now[0] += timedelta(seconds=qq_channel._MSG_SEQ_TTL_SECONDS + 120)
    assert ch._get_next_msg_seq("fresh") == 1

    assert dict.__len__(ch._msg_seq_counter) == 1
