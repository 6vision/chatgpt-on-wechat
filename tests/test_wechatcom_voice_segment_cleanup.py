# encoding:utf-8
"""A WeCom voice reply removes the source, the .amr and every split segment."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.context import Context
from bridge.reply import Reply, ReplyType
from channel.wechat_kf import wechat_kf_channel as kf_module
from channel.wechatcom import wechatcomapp_channel as app_module


def _app_channel():
    cls = app_module.WechatComAppChannel.__wrapped__
    channel = cls.__new__(cls)
    channel.agent_id = "1000002"
    return channel


def _kf_channel():
    cls = kf_module.WechatKfChannel.__wrapped__
    channel = cls.__new__(cls)
    channel._send_voice = MagicMock()
    return channel


@pytest.mark.parametrize("module,make_channel", [(app_module, _app_channel), (kf_module, _kf_channel)])
@pytest.mark.parametrize("segment_count", [0, 3])
def test_voice_reply_leaves_no_audio_files(tmp_path, module, make_channel, segment_count):
    source = tmp_path / "reply.wav"
    source.write_bytes(b"audio")
    amr_file = str(tmp_path / "reply.amr")
    segments = [str(tmp_path / f"reply_{i}.amr") for i in range(segment_count)]
    for path in segments:
        open(path, "wb").close()
    files = segments or [amr_file]

    channel = make_channel()
    channel.client = MagicMock()
    channel.client.media.upload.return_value = {"media_id": "m"}
    context = Context()
    context["receiver"] = "user-1"
    context["external_userid"] = "user-1"
    context["open_kfid"] = "kf-1"

    with patch.object(module, "any_to_amr", lambda src, dst: open(dst, "wb").close()), \
            patch.object(module, "split_audio", return_value=(1000, files)), \
            patch.object(module.time, "sleep"):
        channel.send(Reply(ReplyType.VOICE, str(source)), context)

    assert channel.client.media.upload.call_count == len(files)
    assert os.listdir(tmp_path) == []
