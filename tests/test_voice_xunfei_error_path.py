# encoding:utf-8
"""textToVoice returns an ERROR reply and logs the exception when building the file name fails."""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.reply import ReplyType
from voice.xunfei import xunfei_voice as xv


def test_tmp_dir_failure_returns_error_reply_and_logs_cause():
    voice = xv.XunfeiVoice.__new__(xv.XunfeiVoice)
    voice.APPID, voice.APIKey, voice.APISecret = "appid", "apikey", "apisecret"
    voice.BusinessArgsTTS = {"aue": "lame", "vcn": "xiaoyan"}
    tmp_dir = MagicMock()
    tmp_dir.return_value.path.side_effect = OSError("no writable data root")

    with patch.object(xv, "TmpDir", tmp_dir), patch.object(xv, "xunfei_tts"), \
            patch.object(xv, "logger") as logger:
        reply = voice.textToVoice("hello")

    assert reply.type == ReplyType.ERROR
    assert "no writable data root" in logger.error.call_args.args[0]
