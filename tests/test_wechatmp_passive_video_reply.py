"""A cached wechatmp video must reach the user, and its material must be freed.

``wechatmp_channel.py`` uploads a video reply to the account's *permanent*
material store and caches a ``("video", media_id)`` segment for the passive
replier. ``passive_reply.py`` only knew how to render ``text``, ``voice`` and
``image``, so the segment was popped, matched no branch and fell through to the
trailing ``return "success"``: WeChat was answered with an empty body, the user
saw a blank reply, and not one line was logged. Worse, the ``voice`` and
``image`` branches are the ones that schedule ``delete_media``, so the uploaded
video was never released and stayed in the material store forever.

``passive_reply`` imports ``web`` at module scope, so a stub has to be in
``sys.modules`` before that import. The real ``web.py`` *is* installed here, so
-- unlike the ``try: import web / except ImportError`` guard the other modules
use -- installing the stub has to be unconditional for it to take effect.
"""

import asyncio
import importlib
import sys
import types
from collections import defaultdict

import pytest

TEXT_XML = (
    b"<xml>"
    b"<ToUserName><![CDATA[gh_test]]></ToUserName>"
    b"<FromUserName><![CDATA[oUser1]]></FromUserName>"
    b"<CreateTime>1700000000</CreateTime>"
    b"<MsgType><![CDATA[text]]></MsgType>"
    b"<Content><![CDATA[hi]]></Content>"
    b"<MsgId>1234567890</MsgId>"
    b"</xml>"
)

FROM_USER = "oUser1"
MEDIA_ID = "MEDIA-VIDEO-1"


class _Args(dict):
    """``web.input()`` hands over a mapping that also answers attributes."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


@pytest.fixture
def web_stub(monkeypatch):
    """A ``web`` module good enough for a single POST, with no request context."""
    stub = types.ModuleType("web")
    stub.ctx = types.SimpleNamespace(env={})
    stub.data = lambda: TEXT_XML
    stub.input = lambda **kwargs: _Args(signature="sig", timestamp="1", nonce="n")
    stub.Forbidden = type("Forbidden", (Exception,), {})
    monkeypatch.setitem(sys.modules, "web", stub)
    return stub


@pytest.fixture
def passive_reply(web_stub, monkeypatch):
    """``passive_reply`` imported against the stub.

    Nothing else in the suite imports this module -- web.py resolves it by
    string at startup -- so dropping it from ``sys.modules`` first is enough to
    make it bind the stubbed ``web``.

    The name is then set explicitly because ``from channel.wechatmp.common
    import *`` re-binds the module-global ``web`` after the module-scope
    ``import web``, to whatever ``common`` captured when *it* was first
    imported. Whichever test happens to import ``wechatmp_channel`` first --
    and the real ``web.py`` is importable here, so that is the real one --
    would otherwise decide which ``web`` this module gets to call.
    """
    sys.modules.pop("channel.wechatmp.passive_reply", None)
    module = importlib.import_module("channel.wechatmp.passive_reply")
    monkeypatch.setattr(module, "web", web_stub, raising=False)
    yield module
    sys.modules.pop("channel.wechatmp.passive_reply", None)


class FakeChannel:
    """Only the passive-reply state that ``Query.POST`` actually touches."""

    def __init__(self, segments):
        self.crypto = None
        self.cache_dict = defaultdict(list)
        self.cache_dict[FROM_USER].extend(segments)
        self.running = set()
        self.request_cnt = {}
        self.client = object()
        self.delete_media_loop = object()
        self.deleted = []

    async def delete_media(self, media_id):
        self.deleted.append(media_id)


def _post(module, monkeypatch, segments):
    """Drive one POST over ``segments`` and report what came back."""
    channel = FakeChannel(segments)
    scheduled = []
    drain = asyncio.new_event_loop()
    try:

        def run_coroutine_threadsafe(coro, loop):
            scheduled.append(loop)
            # Production hands the coroutine to a background thread that
            # sleeps 10s before calling the material API. The fake resolves
            # straight away, so the test can assert on what was scheduled.
            drain.run_until_complete(coro)

        monkeypatch.setattr(module.asyncio, "run_coroutine_threadsafe", run_coroutine_threadsafe)
        monkeypatch.setattr(module, "WechatMPChannel", lambda: channel)
        monkeypatch.setattr(module, "verify_server", lambda args: "ok")
        result = module.Query().POST()
    finally:
        drain.close()

    # POST swallows everything and hands the exception back as the body, so an
    # unasserted setup mistake would otherwise look like a dropped reply.
    assert not isinstance(result, Exception), "POST raised: %r" % (result,)
    return result, channel, scheduled


def test_a_cached_video_is_rendered_instead_of_being_dropped(passive_reply, monkeypatch):
    result, channel, _scheduled = _post(passive_reply, monkeypatch, [("video", MEDIA_ID)])

    assert result != "success", "the segment fell through to the bare 'success' acknowledgement"
    assert "<MsgType><![CDATA[video]]></MsgType>" in result
    assert "<MediaId><![CDATA[%s]]></MediaId>" % MEDIA_ID in result
    assert FROM_USER not in channel.cache_dict, "the segment was popped, so the cache entry goes with it"


def test_a_delivered_video_schedules_its_material_for_deletion(passive_reply, monkeypatch):
    _result, channel, scheduled = _post(passive_reply, monkeypatch, [("video", MEDIA_ID)])

    assert scheduled == [channel.delete_media_loop]
    assert channel.deleted == [MEDIA_ID], "the permanent material was never released"


@pytest.mark.parametrize("kind", ["video", "image", "voice"])
def test_every_media_kind_is_drained_exactly_the_same_way(passive_reply, monkeypatch, kind):
    _result, channel, scheduled = _post(passive_reply, monkeypatch, [(kind, MEDIA_ID)])

    assert scheduled == [channel.delete_media_loop]
    assert channel.deleted == [MEDIA_ID]


def test_a_segment_that_cannot_be_rendered_still_releases_its_media(passive_reply, monkeypatch):
    """An unknown segment is still an upload sitting in the permanent store."""
    result, channel, scheduled = _post(passive_reply, monkeypatch, [("sticker", MEDIA_ID)])

    assert result == "success"
    assert scheduled == [channel.delete_media_loop]
    assert channel.deleted == [MEDIA_ID]
