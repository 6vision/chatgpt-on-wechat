"""Slack workspace notices must not be answered as user prompts.

``_handle_message_event`` only dropped the ``bot_message``, ``message_changed`` and
``message_deleted`` subtypes. Slack also delivers ``channel_join``, ``channel_topic``,
``pinned_item`` and the like as ``message`` events that carry a ``user`` and a ``text``,
so with ``slack_group_trigger: all`` the agent replied to "<@U1> has joined the channel".
"""
import pytest

from channel.slack import slack_channel as mod


def _channel(monkeypatch):
    monkeypatch.setattr(mod, "conf", lambda: {"slack_group_trigger": "all"})
    cls = mod.SlackChannel.__wrapped__
    ch = cls.__new__(cls)
    ch.bot_user_id = "UBOT"
    handled = []
    ch._handle_event = lambda event, is_group: handled.append(event["text"])
    return ch, handled


def _event(subtype=None, text="hello"):
    event = {"type": "message", "user": "U123", "channel": "C1", "channel_type": "channel",
             "ts": "1.1", "text": text}
    if subtype:
        event["subtype"] = subtype
    return event


@pytest.mark.parametrize("subtype", ["channel_join", "channel_leave", "channel_topic",
                                     "channel_purpose", "channel_name", "pinned_item"])
def test_workspace_notices_are_not_forwarded(monkeypatch, subtype):
    ch, handled = _channel(monkeypatch)

    ch._handle_message_event(_event(subtype, "notice"))

    assert handled == []


@pytest.mark.parametrize("subtype", [None, "file_share", "thread_broadcast"])
def test_user_messages_are_still_forwarded(monkeypatch, subtype):
    ch, handled = _channel(monkeypatch)

    ch._handle_message_event(_event(subtype, "question"))

    assert handled == ["question"]


@pytest.mark.parametrize("subtype", ["bot_message", "message_changed", "message_deleted"])
def test_previously_filtered_subtypes_stay_filtered(monkeypatch, subtype):
    ch, handled = _channel(monkeypatch)

    ch._handle_message_event(_event(subtype))

    assert handled == []
