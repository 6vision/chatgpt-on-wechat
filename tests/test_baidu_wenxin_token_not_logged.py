# encoding:utf-8
"""A failed Wenxin call must mask credentials from the URL in both the log and the reply."""

import os
import sys
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.baidu import baidu_wenxin as baidu_mod
from models.baidu.baidu_wenxin import BaiduWenxinBot

SECRET = "BAIDU_SECRET_DO_NOT_SHOW"


@pytest.mark.parametrize("failing,url", [
    ("request", f"/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/ernie?access_token={SECRET}"),
    ("post", f"/oauth/2.0/token?grant_type=client_credentials&client_id=AK&client_secret={SECRET}"),
])
def test_failure_does_not_expose_credentials(monkeypatch, failing, url):
    def boom(*args, **kwargs):
        raise requests.exceptions.ConnectionError(f"Max retries exceeded with url: {url}")

    token_response = MagicMock()
    token_response.json.return_value = {"access_token": SECRET}
    monkeypatch.setattr(baidu_mod, "conf", lambda: {})
    monkeypatch.setattr(baidu_mod.requests, "post", MagicMock(return_value=token_response))
    monkeypatch.setattr(baidu_mod.requests, failing, boom)
    logger = MagicMock()
    monkeypatch.setattr(baidu_mod, "logger", logger)

    bot = BaiduWenxinBot.__new__(BaiduWenxinBot)
    bot.sessions, bot.prompt_enabled = MagicMock(), False
    result = bot.reply_text(MagicMock(session_id="u1", model="ernie", messages=[]))

    assert result["content"].startswith("出错了")
    assert "=***" in result["content"]
    assert SECRET not in result["content"]
    assert SECRET not in str(logger.mock_calls)
