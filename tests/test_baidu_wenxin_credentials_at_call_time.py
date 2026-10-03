# encoding:utf-8
"""The Wenxin credentials must be read when the access token is requested.

`models/baidu/baidu_wenxin.py` used to capture `BAIDU_API_KEY` and
`BAIDU_SECRET_KEY` at module import time. The web console, though, updates the
live `conf()` dict in place -- `channel/web/api/config.py` does
`local_config = conf()` and then assigns into it -- so a credential rotated in
the console changed what `conf()` returned without touching the two constants.
The bot kept authenticating with the pair captured on first import, and the
resulting token failure pointed nowhere near the stale credential.

Reading the keys where the OAuth request is built is what every other provider
here already does: `models/deepseek/deepseek_bot.py` and
`models/moonshot/moonshot_bot.py` both read their key from inside an `api_key`
property rather than at import.
"""

import models.baidu.baidu_wenxin as baidu_wenxin
from models.baidu.baidu_wenxin import BaiduWenxinBot

TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"

KEY_AT_STARTUP = "KEY-SET-AT-STARTUP"
SECRET_AT_STARTUP = "SECRET-SET-AT-STARTUP"
KEY_ROTATED = "KEY-ROTATED-IN-CONSOLE"
SECRET_ROTATED = "SECRET-ROTATED-IN-CONSOLE"


def _live_config(api_key, secret_key):
    """Stand in for the live `conf()` dict, which the console mutates in place."""
    return {
        "baidu_wenxin_api_key": api_key,
        "baidu_wenxin_secret_key": secret_key,
    }


def _stub_token_request(monkeypatch, live):
    """Point the module at `live` and record the OAuth request instead of sending it."""
    monkeypatch.setattr(baidu_wenxin, "conf", lambda: live)

    sent = []

    class _Response:
        @staticmethod
        def json():
            return {"access_token": "token-abc"}

    def fake_post(url, params=None, timeout=None):
        sent.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        return _Response()

    monkeypatch.setattr(baidu_wenxin.requests, "post", fake_post)

    # get_access_token touches no instance state, so skip __init__ and the
    # session manager it would otherwise need built.
    return sent, BaiduWenxinBot.__new__(BaiduWenxinBot)


def test_credentials_rotated_at_runtime_are_the_ones_sent(monkeypatch):
    """A console rotation takes effect on the next token request, no restart."""
    live = _live_config(KEY_AT_STARTUP, SECRET_AT_STARTUP)
    sent, bot = _stub_token_request(monkeypatch, live)

    assert bot.get_access_token() == "token-abc"
    assert sent[-1]["params"]["client_id"] == KEY_AT_STARTUP
    assert sent[-1]["params"]["client_secret"] == SECRET_AT_STARTUP

    # Exactly what the console POST handler does to the running process.
    live["baidu_wenxin_api_key"] = KEY_ROTATED
    live["baidu_wenxin_secret_key"] = SECRET_ROTATED

    assert bot.get_access_token() == "token-abc"
    assert sent[-1]["params"]["client_id"] == KEY_ROTATED
    assert sent[-1]["params"]["client_secret"] == SECRET_ROTATED


def test_the_module_does_not_snapshot_the_credentials_at_import():
    """Structural guard on the root cause: nothing to go stale, so nothing can.

    The behavioural test above is the one that matters; this pins the shape that
    made the staleness possible in the first place.
    """
    assert not hasattr(baidu_wenxin, "BAIDU_API_KEY")
    assert not hasattr(baidu_wenxin, "BAIDU_SECRET_KEY")


def test_the_oauth_request_is_unchanged(monkeypatch):
    """Moving the reads must not alter the request the bot sends."""
    live = _live_config(KEY_AT_STARTUP, SECRET_AT_STARTUP)
    sent, bot = _stub_token_request(monkeypatch, live)

    assert bot.get_access_token() == "token-abc"
    assert sent[-1] == {
        "url": TOKEN_URL,
        "params": {
            "grant_type": "client_credentials",
            "client_id": KEY_AT_STARTUP,
            "client_secret": SECRET_AT_STARTUP,
        },
        "timeout": 180,
    }