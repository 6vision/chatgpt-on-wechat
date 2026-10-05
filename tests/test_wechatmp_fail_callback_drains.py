"""A failed task must not leave the user stuck.

_fail_callback logs "dropping" for an undrained cache entry and then discards
only `running`. passive_reply's entry gate starts a task only when the cache is
empty *and* the user is not running, so a leftover entry plus a cleared
`running` closes the gate: the next message skips the agent and drains the
stale text, answering the question that just failed.
"""
import asyncio
import unittest
from collections import defaultdict
from unittest.mock import patch

from channel.wechatmp import wechatmp_channel as wm

# @singleton rebinds the name to get_instance(); the class is on __wrapped__.
W = wm.WechatMPChannel.__wrapped__

KEY = "oUser123"


class Msg:
    msg_id = "m1"
    from_user_id = KEY


def _context():
    return {"msg": Msg()}


def _channel():
    ch = W.__new__(W)
    ch.passive_reply = True
    ch.cache_dict = defaultdict(list)
    ch.running = set()
    ch.request_cnt = {}
    return ch


def _entry_gate(channel, from_user=KEY, content="hello", message_id="m2"):
    """passive_reply.py:51-54, transcribed.

    A new agent task starts only when the cache is empty and the user is not
    already running.
    """
    return (
        channel.cache_dict.get(from_user) is None
        and from_user not in channel.running
        or content.startswith("#")
        and message_id not in channel.request_cnt
    )


class FailCallbackDrainsTest(unittest.TestCase):
    def _fail(self, channel, exc=RuntimeError("stream died")):
        W._fail_callback(channel, "s1", exc, _context())

    def test_a_failed_task_leaves_the_next_message_free_to_start(self):
        channel = _channel()
        channel.running.add(KEY)
        channel.cache_dict[KEY].append(("text", "first chunk"))

        self._fail(channel)

        self.assertNotIn(
            KEY, channel.cache_dict,
            "the stale segment survived, so it is drained as the answer to the "
            "next message",
        )
        self.assertNotIn(KEY, channel.running)
        self.assertTrue(
            _entry_gate(channel),
            "the user's next message will not reach the agent",
        )

    def test_the_entry_is_gone_rather_than_left_empty(self):
        # Not just empty: absent. cache_dict is a defaultdict, so an entry that
        # merely held an empty list would still be created again on the next
        # lookup and the gate would read the same way.
        channel = _channel()
        channel.running.add(KEY)
        channel.cache_dict[KEY].append(("text", "first chunk"))

        self._fail(channel)

        self.assertNotIn(KEY, channel.cache_dict)
        self.assertIsNone(channel.cache_dict.get(KEY))

    def test_a_permanent_media_item_is_released(self):
        # 5 of the 6 cache sites hold a media_id uploaded to the permanent
        # material store, so a leftover entry leaks it. passive_reply releases
        # these with delete_media; the discard has to do the same.
        channel = _channel()
        channel.running.add(KEY)
        channel.delete_media_loop = asyncio.new_event_loop()
        channel.cache_dict[KEY].extend(
            [("image", "MEDIA_IMAGE"), ("video", "MEDIA_VIDEO")]
        )

        # Record what delete_media was asked to release. It has to be a real
        # coroutine function, since the production code hands its result
        # straight to run_coroutine_threadsafe.
        released = []

        async def _delete(media_id):
            released.append(media_id)

        channel.delete_media = _delete

        loop = asyncio.new_event_loop()
        try:
            def _run(coro, target_loop):
                loop.run_until_complete(coro)

            with patch.object(wm.asyncio, "run_coroutine_threadsafe", side_effect=_run):
                self._fail(channel)
        finally:
            loop.close()

        self.assertEqual(
            released, ["MEDIA_IMAGE", "MEDIA_VIDEO"],
            "a cached media item was left in the permanent material store",
        )

    def test_a_failure_with_nothing_cached_is_unaffected(self):
        channel = _channel()
        channel.running.add(KEY)

        self._fail(channel)

        self.assertNotIn(KEY, channel.running)
        self.assertTrue(_entry_gate(channel))

    def test_the_callback_never_raises_on_an_already_drained_entry(self):
        # The success callback runs first on some paths, and passive_reply
        # deletes the entry as it drains; the discard has to tolerate both.
        channel = _channel()
        channel.running.add(KEY)
        channel.cache_dict[KEY].append(("text", "only chunk"))

        # Nothing cached the second time round, so the discard sees an absent
        # entry. It has to be a no-op rather than a KeyError.
        self._fail(channel)
        self._fail(channel)

        self.assertNotIn(KEY, channel.cache_dict)

    def test_the_failure_is_still_recorded(self):
        channel = _channel()
        channel.running.add(KEY)
        channel.cache_dict[KEY].append(("text", "chunk"))

        with patch.object(wm.logger, "exception") as logged:
            self._fail(channel)

        self.assertTrue(logged.called, "the traceback was swallowed")


if __name__ == "__main__":
    unittest.main()
