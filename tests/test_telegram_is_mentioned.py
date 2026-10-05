"""``_is_mentioned`` handles PTB's tuple entities next to list caption entities."""

from types import SimpleNamespace

import pytest

pytest.importorskip("telegram", reason="python-telegram-bot not installed")

from telegram import MessageEntity  # noqa: E402

telegram_channel = pytest.importorskip("channel.telegram.telegram_channel")
TelegramChannel = telegram_channel.TelegramChannel.__wrapped__


def _msg(text=None, caption=None, entities=None, caption_entities=None):
    return SimpleNamespace(text=text, caption=caption, entities=entities, caption_entities=caption_entities)


@pytest.mark.parametrize("msg, expected", [
    (_msg(text="hello @someone", entities=(MessageEntity(type="mention", offset=6, length=8),)), False),
    (_msg(caption="look @someone", caption_entities=[MessageEntity(type="mention", offset=5, length=8)]), False),
    (_msg(text="hey @ourbot please"), True),
    (_msg(caption="hey @ourbot"), True),
    (_msg(text="nothing here"), False),
    (_msg(), False),
])
def test_is_mentioned(msg, expected):
    assert TelegramChannel._is_mentioned(msg, "ourbot") is expected
