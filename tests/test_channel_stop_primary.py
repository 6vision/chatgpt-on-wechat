"""Stopping a channel must release the primary-channel reference.

``stop()`` popped the channel out of the registry and then asked the registry
whether the primary was that channel -- which it can no longer be, because the
entry is gone. So ``_primary_channel`` was never cleared. Because ``start()``
only adopts a primary ``if _primary_channel is None``, a stale reference also
blocked ``restart()`` from replacing it, and ``mgr.channel`` went on handing out
a stopped channel instance for the rest of the process.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeChannel:
    def __init__(self, name):
        self.name = name
        self.cloud_mode = False
        self.running = False

    def startup(self):
        self.running = True

    def stop(self):
        self.running = False


class ChannelStopPrimaryTest(unittest.TestCase):

    def setUp(self):
        import app
        self.app = app
        patcher = patch.object(
            app.channel_factory, "create_channel", side_effect=lambda name: FakeChannel(name)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mgr = app.ChannelManager()

    def _join(self):
        for th in list(self.mgr._threads.values()):
            th.join(timeout=5)

    def test_stopping_the_primary_clears_the_reference(self):
        self.mgr.start(["qq", "web"])
        self._join()
        primary = self.mgr.channel
        self.assertIsNotNone(primary)

        self.mgr.stop("qq")
        self._join()

        self.assertIsNone(self.mgr.channel, "mgr.channel still points at a stopped channel")
        self.assertIsNone(self.mgr._primary_channel)

    def test_stopping_a_non_primary_leaves_the_primary_alone(self):
        self.mgr.start(["web", "qq"])
        self._join()
        primary = self.mgr.channel
        self.assertIsNotNone(primary)

        self.mgr.stop("web")
        self._join()

        self.assertIs(self.mgr.channel, primary)
        self.assertIs(self.mgr._primary_channel, primary)

    def test_stop_all_clears_the_reference(self):
        self.mgr.start(["qq", "web"])
        self._join()
        self.assertIsNotNone(self.mgr.channel)

        self.mgr.stop()
        self._join()

        self.assertIsNone(self.mgr.channel)

    def test_restart_adopts_the_new_instance(self):
        self.mgr.start(["qq"])
        self._join()
        original = self.mgr.channel
        self.assertIsNotNone(original)

        self.mgr.restart("qq")
        self._join()

        self.assertIsNotNone(self.mgr.channel, "mgr.channel is None after a restart")
        self.assertIsNot(self.mgr.channel, original, "mgr.channel still hands out the old instance")
        self.assertTrue(self.mgr.channel.running)
