# encoding:utf-8
"""ChatChannel._generate_reply when speech-to-text fails.

build_voice_to_text is not failure-safe either: an unknown vendor raises from
the voice factory, several vendors (edge, elevenlabs) answer None because
their voiceToText is a no-op, and a vendor network error escapes. Unprotected,
the exception reached _fail_callback (log only) and the user lost the turn; a
None answer crashed on reply.type. _safe_text_to_voice guards the TTS side of
the same turn; _safe_voice_to_text guards its sibling.
"""
import pytest

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel import chat_channel as mod


class _PassThroughPlugins:
    def emit_event(self, e_context):
        return e_context


class _FakeMsg:
    def prepare(self):
        pass


@pytest.fixture
def channel(monkeypatch):
    monkeypatch.setattr(mod, "PluginManager", _PassThroughPlugins)
    # Skip __init__: it starts the consumer thread, which this test does not need.
    ch = mod.ChatChannel.__new__(mod.ChatChannel)
    ch.NOT_SUPPORT_REPLYTYPE = []
    return ch


def _voice_input_context():
    """A voice message, as _generate_reply sees it on the VOICE branch."""
    return Context(ContextType.VOICE, "/tmp/no-such-voice-input.mp3", kwargs={"msg": _FakeMsg()})


def _patch_stt(monkeypatch, voice_to_text):
    # The call goes through super(), so the stub sits on the base class.
    monkeypatch.setattr(mod.Channel, "build_voice_to_text", voice_to_text)


def _vendor_raises(*args):
    raise RuntimeError  # voice/factory.py raises bare for an unknown vendor


def _vendor_answers_none(*args):
    return None  # edge / elevenlabs: voiceToText is an unimplemented no-op


@pytest.mark.parametrize("voice_to_text", [_vendor_raises, _vendor_answers_none],
                         ids=["vendor-raise", "none-reply"])
def test_failed_stt_answers_an_error_instead_of_losing_the_turn(channel, monkeypatch, voice_to_text):
    _patch_stt(monkeypatch, voice_to_text)

    reply = channel._generate_reply(_voice_input_context())

    assert reply.type == ReplyType.ERROR
    assert reply.content


def test_successful_stt_still_hands_the_transcript_to_the_text_branch(channel, monkeypatch):
    """The happy path is unchanged: the transcript drives a normal reply."""
    _patch_stt(monkeypatch, lambda *args: Reply(ReplyType.TEXT, " transcribed text "))
    seen = {}
    monkeypatch.setattr(
        channel, "_compose_context",
        lambda ctype, content, **kwargs: seen.update(type=ctype, content=content),
    )

    channel._generate_reply(_voice_input_context())

    assert seen["type"] == ContextType.TEXT
    assert seen["content"] == " transcribed text "
