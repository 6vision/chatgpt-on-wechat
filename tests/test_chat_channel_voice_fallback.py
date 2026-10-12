# encoding:utf-8
"""ChatChannel._decorate_reply when text-to-voice synthesis fails.

build_text_to_voice is not failure-safe: an unknown vendor raises from the
voice factory and custom vendors answer ERROR when misconfigured.
Unprotected, the exception reached _fail_callback (log only) and the user
lost the turn; the ERROR Reply replaced the answer with a generic error.
voice_to_text already degrades gracefully in _generate_reply.
"""
import pytest

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel import chat_channel as mod


class _PassThroughPlugins:
    def emit_event(self, e_context):
        return e_context


@pytest.fixture
def channel(monkeypatch):
    monkeypatch.setattr(mod, "PluginManager", _PassThroughPlugins)
    # Skip __init__: it starts the consumer thread, which this test does not need.
    ch = mod.ChatChannel.__new__(mod.ChatChannel)
    ch.NOT_SUPPORT_REPLYTYPE = []
    return ch


def _voice_context():
    """A single chat that asked for voice replies (always_reply_voice)."""
    return Context(ContextType.TEXT, "hi", kwargs={"desire_rtype": ReplyType.VOICE})


def _patch_tts(monkeypatch, text_to_voice):
    # The call goes through super(), so the stub sits on the base class; conf is pinned.
    monkeypatch.setattr(mod.Channel, "build_text_to_voice", text_to_voice)
    monkeypatch.setattr(mod, "conf", lambda: {"single_chat_reply_prefix": "", "single_chat_reply_suffix": ""})


def _vendor_raises(*args):
    raise RuntimeError  # voice/factory.py raises bare for an unknown vendor


def _vendor_answers_error(*args):
    return Reply(ReplyType.ERROR, "遇到了一点小问题，请稍后再问我吧")  # CustomVoice.textToVoice


@pytest.mark.parametrize("text_to_voice", [_vendor_raises, _vendor_answers_error],
                         ids=["vendor-raise", "error-reply"])
def test_failed_tts_keeps_the_text_reply(channel, monkeypatch, text_to_voice):
    _patch_tts(monkeypatch, text_to_voice)

    reply = channel._decorate_reply(_voice_context(), Reply(ReplyType.TEXT, "the answer"))

    assert reply.type == ReplyType.TEXT
    assert reply.content == "the answer"
    assert "遇到了一点小问题" not in reply.content


def test_successful_tts_still_returns_the_voice_reply(channel, monkeypatch):
    """The happy path is unchanged: voice reply plus preserved text."""
    _patch_tts(monkeypatch, lambda *args: Reply(ReplyType.VOICE, "/tmp/reply.mp3"))
    context = _voice_context()

    reply = channel._decorate_reply(context, Reply(ReplyType.TEXT, "the answer"))

    assert reply.type == ReplyType.VOICE
    assert reply.content == "/tmp/reply.mp3"
    assert context["voice_reply_text"] == "the answer"
