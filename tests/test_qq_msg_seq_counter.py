"""QQ passive replies must stay sequenced without remembering every message.

``msg_seq`` orders the replies a bot sends back for one inbound message, and the
counter is keyed by that message's id, so an entry only has to outlive the reply
it belongs to. It used to be a plain dict that never shed an entry, so a bot
that stayed connected accumulated one entry (plus the id string) for every
message it had ever answered, for the life of the process.

Bounding it must not disturb the sequence itself: repeated replies to one
message have to keep counting up from 1, or QQ sees a repeat of a number it has
already used for that message and drops the reply.
"""

from collections import OrderedDict

from channel.qq import qq_channel


def _make_channel():
    """A bare channel holding only what ``_get_next_msg_seq`` touches."""
    # @singleton hands back a factory function; the class sits on __wrapped__.
    cls = qq_channel.QQChannel.__wrapped__
    ch = cls.__new__(cls)
    ch._msg_seq_counter = OrderedDict()
    return ch


def test_the_counter_does_not_grow_with_every_message_answered():
    ch = _make_channel()

    for i in range(5000):
        ch._get_next_msg_seq(f"msg-{i}")

    assert len(ch._msg_seq_counter) <= 1024, (
        f"one entry per message ever answered: {len(ch._msg_seq_counter)} kept for 5000 messages"
    )


def test_the_message_just_answered_is_the_one_still_tracked():
    """What gets forgotten has to be the past, not the reply in progress."""
    ch = _make_channel()

    for i in range(5000):
        ch._get_next_msg_seq(f"msg-{i}")

    assert "msg-4999" in ch._msg_seq_counter
    assert ch._get_next_msg_seq("msg-4999") == 2
    assert "msg-0" not in ch._msg_seq_counter


def test_replies_to_one_message_keep_counting_up():
    ch = _make_channel()

    assert ch._get_next_msg_seq("msg-1") == 1
    assert ch._get_next_msg_seq("msg-1") == 2
    assert ch._get_next_msg_seq("msg-1") == 3
    assert len(ch._msg_seq_counter) == 1


def test_each_message_starts_at_one():
    ch = _make_channel()

    assert ch._get_next_msg_seq("msg-1") == 1
    assert ch._get_next_msg_seq("msg-2") == 1


def test_a_reply_interleaved_with_new_messages_keeps_counting():
    """A reply split over several sends must not have its count reset.

    Other messages arriving between two replies to the same message -- other
    users talking, or a second group -- must not disturb the count, or QQ sees
    a msg_seq it has already used for that message and drops the reply.
    """
    ch = _make_channel()

    assert ch._get_next_msg_seq("msg-1") == 1
    for i in range(5):
        ch._get_next_msg_seq(f"other-{i}")
    assert ch._get_next_msg_seq("msg-1") == 2
