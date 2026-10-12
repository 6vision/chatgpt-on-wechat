"""A finished WeCom turn must free its stream state and close the stream,
whatever the reply type, including when the media send raises."""
import pytest

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.wecom_bot.wecom_bot_channel import WecomBotChannel
from channel.wecom_bot.wecom_bot_message import WecomBotMessage

REQ_ID = "req-1"
STREAM_ID = "stream-1"
STREAMED = "Here is the picture."

MEDIA_REPLY_TYPES = [
    ReplyType.IMAGE,
    ReplyType.IMAGE_URL,
    ReplyType.FILE,
    ReplyType.VIDEO,
    ReplyType.VIDEO_URL,
    ReplyType.VOICE,
]


def _channel():
    """A channel with a websocket send stub -- no socket, no thread, no config."""
    cls = WecomBotChannel.__wrapped__  # the class behind the @singleton wrapper
    channel = cls.__new__(cls)
    channel.mode = "websocket"
    channel._stream_states = {}
    return channel


def _context():
    """The reply context: a websocket message that carries a req_id."""
    msg = WecomBotMessage({
        "msgid": "msg-1",
        "create_time": 1758000000,
        "msgtype": "text",
        "chattype": "single",
        "aibotid": "bot-1",
        "chatid": "chat-1",
        "from": {"userid": "user-1"},
        "text": {"content": "draw me a cat"},
    })
    msg.req_id = REQ_ID
    return Context(ContextType.TEXT, msg.content, {
        "msg": msg, "isgroup": False, "receiver": "chat-1",
    })


def _streamed(channel, content=STREAMED):
    """Seed the state _make_stream_callback leaves behind after streaming."""
    channel._stream_states[REQ_ID] = {
        "stream_id": STREAM_ID,
        "committed": content,
        "current": "",
        "last_push_time": 0,
        "last_push_len": 0,
    }


def _collect(channel):
    """Record what send() puts on the wire instead of writing to a socket."""
    sent = []
    channel._ws_send = sent.append
    return sent


def _stub_media_senders(channel):
    """Neutralise the media paths -- they hit the filesystem and the network."""
    for name in ("_send_image", "_send_file", "_send_voice"):
        setattr(channel, name, lambda *args, **kwargs: None)


def _finishes(sent):
    return [d for d in sent
            if d["body"].get("msgtype") == "stream" and d["body"]["stream"]["finish"]]


@pytest.mark.parametrize("rtype", MEDIA_REPLY_TYPES)
def test_a_media_reply_frees_the_state_and_closes_the_stream(rtype):
    channel = _channel()
    _streamed(channel)
    sent = _collect(channel)
    _stub_media_senders(channel)

    channel.send(Reply(rtype, "media"), _context())

    assert REQ_ID not in channel._stream_states, (
        f"a {rtype} reply must not leave its stream state behind -- _stream_states "
        "grows by one accumulated answer per media reply for the life of the process"
    )
    finishes = _finishes(sent)
    assert len(finishes) == 1, f"the stream must be closed exactly once, got {sent}"
    assert finishes[0]["cmd"] == "aibot_respond_msg"
    assert finishes[0]["headers"]["req_id"] == REQ_ID
    assert finishes[0]["body"]["stream"] == {
        "id": STREAM_ID, "finish": True, "content": STREAMED,
    }, "the close packet has to reuse the open stream and keep what was streamed"


def test_the_state_is_freed_even_when_the_media_send_raises():
    channel = _channel()
    _streamed(channel)
    sent = _collect(channel)

    def boom(*args, **kwargs):
        raise RuntimeError("upload failed")

    channel._send_image = boom

    with pytest.raises(RuntimeError):
        channel.send(Reply(ReplyType.IMAGE, "media"), _context())

    assert REQ_ID not in channel._stream_states, (
        "a failed media send must not leak the stream state either"
    )
    assert len(_finishes(sent)) == 1


def test_a_text_reply_still_closes_the_stream_with_the_streamed_content():
    channel = _channel()
    _streamed(channel)
    sent = _collect(channel)

    channel.send(Reply(ReplyType.TEXT, "final text"), _context())

    assert REQ_ID not in channel._stream_states
    finishes = _finishes(sent)
    assert len(finishes) == 1
    assert finishes[0]["body"]["stream"] == {
        "id": STREAM_ID, "finish": True, "content": STREAMED,
    }, "the text path prefers what the agent already streamed over the reply text"


def test_a_text_reply_without_a_stream_falls_back_to_the_reply_content():
    channel = _channel()
    sent = _collect(channel)

    channel.send(Reply(ReplyType.TEXT, "final text"), _context())

    finishes = _finishes(sent)
    assert len(finishes) == 1
    assert finishes[0]["body"]["stream"]["finish"] is True
    assert finishes[0]["body"]["stream"]["content"] == "final text"
    assert len(finishes[0]["body"]["stream"]["id"]) == 16, "a fresh stream id is minted"


def test_a_file_reply_with_a_caption_closes_the_stream_only_once():
    channel = _channel()
    _streamed(channel)
    sent = _collect(channel)
    _stub_media_senders(channel)

    reply = Reply(ReplyType.FILE, "media")
    reply.text_content = "the report"
    channel.send(reply, _context())

    finishes = _finishes(sent)
    assert len(finishes) == 1, f"the caption already closed the stream, got {sent}"
    assert finishes[0]["body"]["stream"]["content"] == STREAMED


def test_a_media_reply_with_nothing_streamed_sends_no_empty_bubble():
    channel = _channel()
    _streamed(channel, content="")
    sent = _collect(channel)
    _stub_media_senders(channel)

    channel.send(Reply(ReplyType.IMAGE, "media"), _context())

    assert REQ_ID not in channel._stream_states
    assert _finishes(sent) == []
