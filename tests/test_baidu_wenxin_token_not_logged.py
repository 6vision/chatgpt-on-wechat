# encoding:utf-8
"""A failed Wenxin call must not hand the access token back in an error reply.

The chat endpoint takes its credential as a query parameter:

    url = ("https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/"
           + session.model + "?access_token=" + access_token)

and requests writes the whole URL, query included, into the message of the
exception it raises when the call fails -- ``Max retries exceeded with url:
/rpc/2.0/.../chat/ernie?access_token=...``. ``receive`` then does two things with
that message:

    logger.warn("[BAIDU] Exception: {}".format(e))
    result = {..., "content": "出错了: {}".format(e)}

so a network blip writes a live credential into run.log -- which the web console
serves as a complete file download -- *and* shows it to the user, because a
zero-token result becomes ``Reply(ReplyType.ERROR, reply_content)``.

``get_access_token`` has the same shape, with ``client_secret`` in the query, and
its failure reaches the same two places. The channels were scrubbed for this
(wechatcom, dingtalk, wechat_kf); the model providers were not.
"""

import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common import utils
from models.baidu import baidu_wenxin as baidu_mod
from models.baidu.baidu_wenxin import BaiduWenxinBot

TOKEN = "BAIDU_ACCESS_TOKEN_DO_NOT_SHOW"
SECRET = "BAIDU_CLIENT_SECRET_DO_NOT_SHOW"


class _RecordingLogger:
    """Stands in for the module logger so the test can read what was written."""

    def __init__(self):
        self.messages = []

    def _record(self, message, *args, **kwargs):
        self.messages.append(str(message))

    debug = info = warning = warn = error = exception = critical = _record


class _Sessions:
    def clear_session(self, session_id):
        pass


class _Session:
    session_id = "u1"
    model = "ernie"
    messages = [{"role": "user", "content": "hi"}]


def _bot():
    bot = BaiduWenxinBot.__new__(BaiduWenxinBot)
    bot.sessions = _Sessions()
    bot.prompt_enabled = False
    bot.get_access_token = lambda: TOKEN
    return bot


def _chat_failure():
    """The shape requests raises when the chat endpoint cannot be reached."""
    return requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='aip.baidubce.com', port=443): Max retries "
        "exceeded with url: /rpc/2.0/ai_custom/v1/wenxinworkshop/chat/ernie"
        f"?access_token={TOKEN} (Caused by NewConnectionError(...))"
    )


def _token_failure():
    """The shape requests raises when the token endpoint cannot be reached."""
    return requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='aip.baidubce.com', port=443): Max retries "
        "exceeded with url: /oauth/2.0/token?grant_type=client_credentials"
        f"&client_id=AK&client_secret={SECRET} (Caused by NewConnectionError(...))"
    )


def test_a_failed_chat_does_not_show_the_access_token(monkeypatch):
    def boom(*args, **kwargs):
        raise _chat_failure()

    monkeypatch.setattr(baidu_mod.requests, "request", boom)
    recorder = _RecordingLogger()
    monkeypatch.setattr(baidu_mod, "logger", recorder)

    result = _bot().reply_text(_Session())

    assert TOKEN not in result["content"], "the access token was shown to the user"
    assert TOKEN not in "\n".join(recorder.messages), "the access token was logged"
    assert "access_token=***" in result["content"], "mask it, do not drop the message"
    assert "出错了" in result["content"]


def test_a_failed_token_request_does_not_show_the_client_secret(monkeypatch):
    """``get_access_token`` carries client_secret in its query string."""
    def boom(*args, **kwargs):
        raise _token_failure()

    monkeypatch.setattr(baidu_mod.requests, "post", boom)
    recorder = _RecordingLogger()
    monkeypatch.setattr(baidu_mod, "logger", recorder)

    bot = _bot()
    del bot.get_access_token  # use the real one, so the request is made
    result = bot.reply_text(_Session())

    assert SECRET not in result["content"], "client_secret was shown to the user"
    assert SECRET not in "\n".join(recorder.messages), "client_secret was logged"
    assert "client_secret=***" in result["content"]


def test_scrub_secrets_leaves_unrelated_text_alone():
    assert utils.scrub_secrets("connection reset by peer") == "connection reset by peer"


def test_scrub_secrets_masks_a_bare_token_query():
    scrubbed = utils.scrub_secrets(f"https://example.invalid/x?access_token={TOKEN}&a=1")
    assert TOKEN not in scrubbed
    assert "&a=1" in scrubbed
