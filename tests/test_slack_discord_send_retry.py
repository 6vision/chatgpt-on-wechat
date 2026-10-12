"""Slack/Discord send failures reach chat_channel._send's retry only when nothing
was delivered: the retry re-sends the whole reply, and a Discord timeout may
still complete on the loop."""
import asyncio
import concurrent.futures
import threading
from types import SimpleNamespace

import pytest

from bridge.reply import Reply, ReplyType
from channel.discord import discord_channel as discord_mod
from channel.discord.discord_channel import DiscordChannel
from channel.slack.slack_channel import SlackChannel

LONG_TEXT = "x\n" * 3000  # several chunks on both channels


class _Sender:
    """Records sends and raises on the ``fail_at``-th call (1-based)."""

    def __init__(self, fail_at):
        self.fail_at = fail_at
        self.sent = []

    def __call__(self, *args, **kwargs):
        if len(self.sent) + 1 == self.fail_at:
            raise RuntimeError("rate limited")
        self.sent.append((args, kwargs))


def _slack(sender):
    ch = SlackChannel.__wrapped__.__new__(SlackChannel.__wrapped__)
    ch._client = SimpleNamespace(chat_postMessage=sender)
    return ch


@pytest.fixture(scope="module")
def loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def _discord(loop, sender):
    async def send(*args, **kwargs):
        sender(*args, **kwargs)

    ch = DiscordChannel.__wrapped__.__new__(DiscordChannel.__wrapped__)
    ch._loop = loop
    ch._client = SimpleNamespace(get_channel=lambda _id: SimpleNamespace(send=send))
    return ch


def test_slack_retries_when_nothing_went_out():
    with pytest.raises(RuntimeError):
        _slack(_Sender(fail_at=1)).send(Reply(ReplyType.TEXT, "hi"), {"slack_channel": "C1"})


def test_slack_does_not_retry_a_partial_reply():
    sender = _Sender(fail_at=2)
    _slack(sender).send(Reply(ReplyType.TEXT, LONG_TEXT), {"slack_channel": "C1"})
    assert len(sender.sent) == 1


def test_slack_success_is_unchanged():
    sender = _Sender(fail_at=0)
    _slack(sender).send(Reply(ReplyType.TEXT, "hi"), {"slack_channel": "C1"})
    assert len(sender.sent) == 1


def test_discord_retries_when_nothing_went_out(loop):
    with pytest.raises(RuntimeError):
        _discord(loop, _Sender(fail_at=1)).send(Reply(ReplyType.TEXT, "hi"), {"discord_channel_id": 1})


def test_discord_does_not_retry_a_partial_reply(loop):
    sender = _Sender(fail_at=2)
    _discord(loop, sender).send(Reply(ReplyType.TEXT, LONG_TEXT), {"discord_channel_id": 1})
    assert len(sender.sent) == 1


def test_discord_does_not_retry_a_timeout(loop, monkeypatch):
    class _Pending:
        def result(self, timeout=None):
            raise concurrent.futures.TimeoutError()

    def schedule(coro, _loop):
        coro.close()
        return _Pending()

    monkeypatch.setattr(discord_mod.asyncio, "run_coroutine_threadsafe", schedule)
    _discord(loop, _Sender(fail_at=0)).send(Reply(ReplyType.TEXT, "hi"), {"discord_channel_id": 1})
