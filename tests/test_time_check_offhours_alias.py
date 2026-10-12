"""Off hours, only the config reload commands get through."""

from unittest.mock import patch

import pytest

from common.time_check import time_checker


class _Msg:
    def __init__(self, content):
        self.content = content


class _Channel:
    reached = False

    @time_checker
    def handle_single(self, msg):
        self.reached = True


def _send(text):
    channel = _Channel()
    conf = {"chat_time_module": True, "chat_start_time": "00:00", "chat_stop_time": "00:01"}
    with patch("common.time_check.config.conf", return_value=conf), \
            patch("common.time_check.time.strftime", return_value="12:00"):
        channel.handle_single(_Msg(text))
    return channel.reached


@pytest.mark.parametrize("text", ["#reconf", "#重载配置", "#更新配置"])
def test_reload_command_passes(text):
    assert _send(text)


@pytest.mark.parametrize("text", ["#resetall", "你好", "#starta"])
def test_other_message_is_refused(text):
    assert not _send(text)
