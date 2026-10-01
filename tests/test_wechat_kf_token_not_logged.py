# encoding:utf-8
"""A failed kf API call must not write the access token into run.log.

Both WeCom kf endpoints take the token as a query parameter:

    url = f"{KF_API_BASE}/sync_msg?access_token={self.client.access_token}"

and requests puts the whole URL, query included, into the message of the
exception it raises when the call fails -- ``Max retries exceeded with url:
/cgi-bin/kf/sync_msg?access_token=...``. Logging that exception raw therefore
writes a live credential into run.log, which the web console serves as a
complete file download (``LogsDownloadHandler``). A single network blip is
enough to leak it. The same URLs were scrubbed in the wechatcom and dingtalk
channels; wechat_kf was missed.
"""

import os
import sys
from types import SimpleNamespace

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.wechat_kf import wechat_kf_channel as kf_mod
from channel.wechat_kf.wechat_kf_channel import WechatKfChannel

TOKEN = "KF_ACCESS_TOKEN_DO_NOT_LOG"


class _RecordingLogger:
    """Stands in for the module logger so the test can read what was written."""

    def __init__(self):
        self.messages = []

    def _record(self, message, *args, **kwargs):
        self.messages.append(str(message))

    debug = info = warning = error = exception = critical = _record


def _connection_error():
    """The shape requests raises when the endpoint cannot be reached."""
    return requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='qyapi.weixin.qq.com', port=443): Max retries "
        f"exceeded with url: /cgi-bin/kf/sync_msg?access_token={TOKEN} "
        "(Caused by NewConnectionError(...))"
    )


def _channel():
    # `@singleton` wraps the class in a factory; `__wrapped__` is the real class.
    cls = WechatKfChannel.__wrapped__
    channel = cls.__new__(cls)
    channel.client = SimpleNamespace(access_token=TOKEN)
    return channel


def test_sync_msg_failure_does_not_log_the_token(monkeypatch):
    def boom(*args, **kwargs):
        raise _connection_error()

    monkeypatch.setattr(kf_mod.requests, "post", boom)
    recorder = _RecordingLogger()
    monkeypatch.setattr(kf_mod, "logger", recorder)

    assert _channel()._call_sync_msg("event-token", "open-kfid", None) is None

    logged = "\n".join(recorder.messages)
    assert TOKEN not in logged, "the access token was written to the log"
    assert "access_token=***" in logged, "the token should be masked, not dropped"


def test_send_msg_failure_does_not_log_the_token(monkeypatch):
    def boom(*args, **kwargs):
        raise _connection_error()

    monkeypatch.setattr(kf_mod.requests, "post", boom)
    recorder = _RecordingLogger()
    monkeypatch.setattr(kf_mod, "logger", recorder)

    result = _channel()._post_send_msg({"msgtype": "text"})

    logged = "\n".join(recorder.messages) + str(result)
    assert TOKEN not in logged, "the access token was written to the log"
    assert "access_token=***" in logged


def test_scrub_secrets_leaves_unrelated_text_alone():
    assert kf_mod._scrub_secrets("connection reset by peer") == "connection reset by peer"


def test_scrub_secrets_masks_a_bare_token_query():
    scrubbed = kf_mod._scrub_secrets(f"https://example.invalid/x?access_token={TOKEN}&a=1")
    assert TOKEN not in scrubbed
    assert "&a=1" in scrubbed
