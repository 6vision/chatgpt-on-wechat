from types import SimpleNamespace
import pytest
from channel.telegram.telegram_channel import TelegramChannel as channel_factory
TelegramChannel = channel_factory.__wrapped__

@pytest.mark.parametrize('text, expected', [('@cowbot_extra hi', False), ('@cowbot2 hi', False), ('@cowbot hi', True), ('@COWBOT, hi', True)])
def test_mentions_match_complete_username(text, expected):
    message = SimpleNamespace(text=text, caption=None, entities=(), caption_entities=())
    assert TelegramChannel._is_mentioned(message, 'cowbot') is expected

def test_stripping_preserves_other_bot_username():
    channel = object.__new__(TelegramChannel)
    channel.bot_username = 'cowbot'
    assert channel._strip_at_mention('@cowbot_extra @cowbot hi') == '@cowbot_extra  hi'
