# encoding:utf-8
"""
Unit tests for voice/pytts/pytts_voice.py.

The non-win32 branch hand-rolls its wait for espeak's coroutine:

    while self.engine.isBusy() or wavFileName not in os.listdir(TmpDir().path()):
        time.sleep(0.1)

That loop had no upper bound, so an espeak coroutine that never reports idle
held the voice thread forever - the in-repo comment already noted the wait
"cannot" terminate in some cases. It also rebuilt a TmpDir and rescanned the
whole directory on every 100ms poll.

``pyttsx3`` is an optional extra, so the engine is replaced with a controllable
fake rather than a real one.
"""
import os
import sys
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType


class _FakeEngine:
    """Records save_to_file calls; busy state and file creation are scripted."""

    def __init__(self):
        self.busy = False
        self.iterate_calls = 0
        self.saved = []

    def setProperty(self, *args, **kwargs):
        pass

    def getProperty(self, *args, **kwargs):
        return []

    def startLoop(self, *args, **kwargs):
        pass

    def save_to_file(self, text, path):
        self.saved.append((text, path))

    def iterate(self):
        self.iterate_calls += 1

    def isBusy(self):
        return self.busy

    def runAndWait(self):
        pass


def _install_pyttsx3():
    mod = types.ModuleType("pyttsx3")
    mod.init = lambda *a, **k: _FakeEngine()
    sys.modules.setdefault("pyttsx3", mod)


_install_pyttsx3()

import voice.pytts.pytts_voice as pytts_voice  # noqa: E402


def _voice():
    """Build a PyttsVoice whose engine is a fresh controllable fake."""
    engine = _FakeEngine()
    with mock.patch.object(pytts_voice, "pyttsx3") as pt:
        pt.init.return_value = engine
        voice = pytts_voice.PyttsVoice()
    voice.engine = engine
    return voice


class TestPyttsVoiceToVoice(unittest.TestCase):
    def setUp(self):
        # Drive the non-win32 branch, which is the one with the hand-rolled wait.
        self.platform = mock.patch.object(pytts_voice.sys, "platform", "linux")
        self.platform.start()
        self.addCleanup(self.platform.stop)
        # Keep the test fast: a 30s bound would be a 30s test.
        patch = mock.patch.object(pytts_voice, "_SYNTHESIS_TIMEOUT_S", 0.35)
        patch.start()
        self.addCleanup(patch.stop)
        patch_poll = mock.patch.object(pytts_voice, "_SYNTHESIS_POLL_S", 0.01)
        patch_poll.start()
        self.addCleanup(patch_poll.stop)

    def test_returns_the_voice_once_the_file_appears(self):
        """The normal path still returns a VOICE reply with a real file."""
        voice = _voice()

        def save_to_file(text, path):
            # A real engine writes the wav; here it lands immediately.
            with open(path, "wb") as f:
                f.write(b"RIFF")

        voice.engine.save_to_file = save_to_file
        voice.engine.busy = False

        reply = voice.textToVoice("hello")
        self.assertEqual(reply.type, ReplyType.VOICE)
        self.assertTrue(os.path.exists(reply.content))

    def test_a_coroutine_that_never_idles_does_not_hang(self):
        """The wait must give up instead of blocking the voice thread forever."""
        voice = _voice()
        voice.engine.busy = True  # never cleared, and no file is ever written
        voice.engine.iterate = lambda: None

        started = time.monotonic()
        reply = voice.textToVoice("hello")
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 5.0, f"textToVoice took {elapsed:.1f}s, so it did not give up")
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_a_coroutine_that_stalls_before_writing_also_gives_up(self):
        voice = _voice()
        voice.engine.busy = False  # reports idle, but the file never appears
        voice.engine.iterate = lambda: None

        started = time.monotonic()
        reply = voice.textToVoice("hello")
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 5.0, f"textToVoice took {elapsed:.1f}s waiting for a missing file")
        self.assertEqual(reply.type, ReplyType.ERROR)

    def test_base_exception_is_not_swallowed(self):
        voice = _voice()

        def interrupt():
            raise KeyboardInterrupt()

        voice.engine.iterate = interrupt
        with self.assertRaises(KeyboardInterrupt):
            voice.textToVoice("hello")


if __name__ == "__main__":
    unittest.main()
