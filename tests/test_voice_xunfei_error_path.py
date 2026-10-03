# encoding:utf-8
"""
Unit tests for the xunfei textToVoice error path.

``XunfeiVoice.textToVoice`` builds ``fileName`` on the first line of its ``try``
and its ``except`` clause then formats that same name::

    fileName = TmpDir().path() + "reply-" + ...
    ...
    except Exception:
        logger.error("[Xunfei] textToVoice error={}".format(fileName))

When the failure happens *on* that first line -- ``TmpDir().path()`` raising on a
full disk, a missing workspace or a read-only data root -- ``fileName`` was never
bound, so the handler itself raised ``UnboundLocalError``. Nothing catches that
inside the method, so it escaped ``textToVoice`` and the trailing ``return reply``
never ran. The user got no reply at all instead of the ERROR reply every other
provider in ``voice/`` returns, and the raise landed on the channel error path
that only logs it.

The same line logged the file name where the exception belonged, so the actual
cause never reached the log: the entry read ``error=reply-1712345678-1234.mp3``.
"""
import logging
import os
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType
from voice.xunfei import xunfei_voice as xv

_ERROR_TEXT = "抱歉，讯飞语音合成失败"


class _TmpDirThatCannotResolve:
    """A TmpDir stand-in that fails the way an unwritable data root does.

    ``TmpDir.path()`` only formats ``tmp_dir()`` into a string, so it is the one
    call in the method that can still be failing before ``fileName`` exists.
    """

    def path(self):
        raise OSError("no writable data root")


class _Collector(logging.Handler):
    """Gather what the 'log' logger was handed.

    ``common.log`` sets ``propagate = False`` and keeps its own handlers, so
    reading the test's stdout would not show whether the exception was logged
    through ``logger`` at all.
    """

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _voice():
    """A XunfeiVoice without running ``__init__``.

    The class only ships a ``config.json.template``, so the real constructor
    disables itself and leaves the credentials unset; the attributes are set
    here because ``textToVoice`` reads all four.
    """
    voice = xv.XunfeiVoice.__new__(xv.XunfeiVoice)
    voice.APPID = "appid"
    voice.APIKey = "apikey"
    voice.APISecret = "apisecret"
    voice.BusinessArgsTTS = {"aue": "lame", "vcn": "xiaoyan"}
    voice.BusinessArgsASR = {"domain": "iat"}
    return voice


class TestXunfeiTextToVoiceErrorPath(unittest.TestCase):
    def test_a_failure_building_the_file_name_returns_an_error_reply(self):
        """The defect: the handler raised UnboundLocalError and the caller got nothing."""
        with unittest.mock.patch.object(xv, "TmpDir", _TmpDirThatCannotResolve):
            with unittest.mock.patch.object(xv, "xunfei_tts"):
                try:
                    reply = _voice().textToVoice("你好")
                except UnboundLocalError as exc:
                    self.fail("textToVoice raised UnboundLocalError from its own "
                              "handler: {}".format(exc))

        self.assertEqual(reply.type, ReplyType.ERROR)
        self.assertEqual(reply.content, _ERROR_TEXT)

    def test_the_underlying_exception_is_logged(self):
        """The log named the file that was never built, so the cause was lost."""
        collector = _Collector()
        log = logging.getLogger("log")
        log.addHandler(collector)
        try:
            with unittest.mock.patch.object(xv, "TmpDir", _TmpDirThatCannotResolve):
                with unittest.mock.patch.object(xv, "xunfei_tts"):
                    _voice().textToVoice("你好")
        finally:
            log.removeHandler(collector)

        logged = "\n".join(collector.messages)
        self.assertIn("no writable data root", logged)
        self.assertNotIn(".mp3", logged)

    def test_a_failure_inside_the_synthesis_still_returns_an_error_reply(self):
        """The control: the path where fileName *is* bound must keep working."""
        def boom(*args, **kwargs):
            raise ConnectionError("connection reset by peer")

        with unittest.mock.patch.object(xv, "TmpDir"):
            with unittest.mock.patch.object(xv, "xunfei_tts", boom):
                reply = _voice().textToVoice("你好")

        self.assertEqual(reply.type, ReplyType.ERROR)
        self.assertEqual(reply.content, _ERROR_TEXT)

    def test_a_successful_synthesis_still_returns_a_voice_reply(self):
        """The control for the guard: the working path must not be swallowed."""
        written = {}

        def fake_tts(appid, apikey, apisecret, args, text, file_name):
            written["file_name"] = file_name

        with unittest.mock.patch.object(xv, "TmpDir"):
            with unittest.mock.patch.object(xv, "xunfei_tts", fake_tts):
                reply = _voice().textToVoice("你好")

        self.assertEqual(reply.type, ReplyType.VOICE)
        self.assertEqual(reply.content, written["file_name"])
        self.assertTrue(written["file_name"].endswith(".mp3"))


if __name__ == "__main__":
    unittest.main()
