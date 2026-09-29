# encoding:utf-8
"""QQ may not refuse the image replies it knows how to send.

``Channel.NOT_SUPPORT_REPLYTYPE`` defaults to ``[VOICE, IMAGE]`` and every
channel that can do better overrides it -- the ten that send images set it to
``[]``, and the two that still cannot send voice (terminal, web console) narrow
it to ``[VOICE]``. ``QQChannel`` never overrides it at all, so it inherits
``[VOICE, IMAGE]`` while implementing ``_send_image`` (URL *and* local file,
via ``_upload_rich_media`` / ``_upload_rich_media_base64``) and video sending.

``ChatChannel._decorate_reply`` therefore rewrites every ``ReplyType.IMAGE``
reply into ``ReplyType.ERROR`` -- "不支持发送的消息类型: ReplyType.IMAGE" --
before ``send`` is ever reached, so the image branch below is dead code and the
user is told the channel cannot do something it can. ``IMAGE_URL`` is a separate
member and is *not* in the list, so images that arrive as a URL are delivered
while images produced locally are refused.
"""
import pytest

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel import chat_channel as chat_mod
from channel.qq import qq_channel as qq_mod


class _PassThroughPlugins:
    def emit_event(self, e_context):
        return e_context


def _qq_class():
    """``@singleton`` hands back a factory function; the class lives in its closure."""
    return next(cell.cell_contents for cell in qq_mod.QQChannel.__closure__
                if isinstance(cell.cell_contents, type))


@pytest.fixture
def channel(monkeypatch):
    monkeypatch.setattr(chat_mod, "PluginManager", _PassThroughPlugins)
    # Skip __init__: it builds the gateway client and its threads.
    cls = _qq_class()
    return cls.__new__(cls)


def test_an_image_reply_is_not_refused(channel):
    reply = channel._decorate_reply(Context(ContextType.TEXT, "hi"),
                                    Reply(ReplyType.IMAGE, "/tmp/pic.png"))

    assert reply.type == ReplyType.IMAGE
    assert reply.content == "/tmp/pic.png"


def test_a_voice_reply_is_still_refused(channel):
    """The control: there is no voice sender here, so voice stays declared."""
    reply = channel._decorate_reply(Context(ContextType.TEXT, "hi"),
                                    Reply(ReplyType.VOICE, "/tmp/reply.mp3"))

    assert reply.type == ReplyType.ERROR
    assert "VOICE" in str(reply.content)
