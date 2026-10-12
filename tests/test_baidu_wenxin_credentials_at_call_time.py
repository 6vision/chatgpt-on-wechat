# encoding:utf-8
"""Wenxin reads its credentials from conf() each time the access token is requested."""
from unittest.mock import MagicMock

import models.baidu.baidu_wenxin as baidu_wenxin
from models.baidu.baidu_wenxin import BaiduWenxinBot


def test_credentials_changed_at_runtime_are_used(monkeypatch):
    live = {"baidu_wenxin_api_key": "KEY-1", "baidu_wenxin_secret_key": "SECRET-1"}
    monkeypatch.setattr(baidu_wenxin, "conf", lambda: live)
    post = MagicMock()
    post.return_value.json.return_value = {"access_token": "token-abc"}
    monkeypatch.setattr(baidu_wenxin.requests, "post", post)
    bot = BaiduWenxinBot.__new__(BaiduWenxinBot)

    assert bot.get_access_token() == "token-abc"
    assert post.call_args.kwargs["params"]["client_id"] == "KEY-1"

    # The web console updates the live conf() dict in place.
    live.update(baidu_wenxin_api_key="KEY-2", baidu_wenxin_secret_key="SECRET-2")
    bot.get_access_token()
    assert post.call_args.kwargs["params"] == {
        "grant_type": "client_credentials", "client_id": "KEY-2", "client_secret": "SECRET-2",
    }
