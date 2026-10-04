"""``_is_mentioned`` must tolerate PTB's mixed entity containers.

Regression: ``(message.entities or []) + (message.caption_entities or [])``
raises ``TypeError: can only concatenate tuple (not list) to tuple`` because in
PTB 22.x ``entities`` is a **tuple** while ``caption_entities`` is a **list**
(or ``None``).  The exception escaped ``_is_mentioned`` and aborted
``_on_message`` for the whole update, so any group message carrying entities
without mentioning the bot could kill the handler before the agent ever saw it.

The first test below fails on the pre-fix code (that is its point) and passes
once both containers are coerced to ``list``.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("telegram", reason="python-telegram-bot not installed")

from telegram import MessageEntity  # noqa: E402

telegram_channel = pytest.importorskip(
    "channel.telegram.telegram_channel",
    reason="python-telegram-bot not installed",
)
# `@singleton` wraps the class in a factory; __wrapped__ is the real class.
TelegramChannel = telegram_channel.TelegramChannel.__wrapped__


def _msg(text=None, caption=None, entities=None, caption_entities=None):
    return SimpleNamespace(
        text=text,
        caption=caption,
        entities=entities,
        caption_entities=caption_entities,
    )


# ---------------------------------------------------------------------------
# the containers (this is the regression the change fixes)
# ---------------------------------------------------------------------------

def test_tuple_entities_without_bot_mention_does_not_raise():
    """tuple entities + caption_entities=None ⇒ old code raised TypeError here."""
    msg = _msg(
        text="hello @someone",
        entities=(MessageEntity(type="mention", offset=6, length=8),),
    )
    assert TelegramChannel._is_mentioned(msg, "ourbot") is False


def test_list_caption_entities_are_handled():
    """photo caption: entities=None, caption_entities is a list."""
    msg = _msg(
        caption="look @someone",
        caption_entities=[MessageEntity(type="mention", offset=5, length=8)],
    )
    assert TelegramChannel._is_mentioned(msg, "ourbot") is False


# ---------------------------------------------------------------------------
# unchanged behaviour
# ---------------------------------------------------------------------------

def test_bot_mention_in_text_is_detected():
    assert TelegramChannel._is_mentioned(_msg(text="hey @ourbot please"), "ourbot") is True


def test_bot_mention_in_caption_is_detected():
    assert TelegramChannel._is_mentioned(_msg(caption="hey @ourbot"), "ourbot") is True


def test_message_without_entities_is_not_a_mention():
    assert TelegramChannel._is_mentioned(_msg(text="nothing here"), "ourbot") is False


def test_empty_message_is_not_a_mention():
    assert TelegramChannel._is_mentioned(_msg(), "ourbot") is False
