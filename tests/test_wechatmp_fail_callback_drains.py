"""A failed task drops the user's cached reply so the next message starts fresh."""

import asyncio
from collections import defaultdict
from unittest.mock import patch

from channel.wechatmp import wechatmp_channel as wm

W = wm.WechatMPChannel.__wrapped__
KEY = "oUser123"


class _Msg:
    msg_id = "m1"
    from_user_id = KEY


def _fail_with_cache(items):
    ch = W.__new__(W)
    ch.passive_reply = True
    ch.cache_dict = defaultdict(list, {KEY: list(items)})
    ch.running = {KEY}
    ch.delete_media_loop = None
    released = []

    async def _delete(media_id):
        released.append(media_id)

    ch.delete_media = _delete
    loop = asyncio.new_event_loop()
    try:
        with patch.object(wm.asyncio, "run_coroutine_threadsafe",
                          side_effect=lambda coro, _loop: loop.run_until_complete(coro)):
            W._fail_callback(ch, "s1", RuntimeError("boom"), {"msg": _Msg()})
            W._fail_callback(ch, "s1", RuntimeError("boom"), {"msg": _Msg()})
    finally:
        loop.close()
    return ch, released


def test_cached_text_is_dropped():
    ch, released = _fail_with_cache([("text", "first chunk")])
    assert KEY not in ch.cache_dict and KEY not in ch.running
    assert released == []


def test_cached_media_is_released():
    ch, released = _fail_with_cache([("image", "MEDIA_IMAGE"), ("text", "t"), ("video", "MEDIA_VIDEO")])
    assert KEY not in ch.cache_dict
    assert released == ["MEDIA_IMAGE", "MEDIA_VIDEO"]
