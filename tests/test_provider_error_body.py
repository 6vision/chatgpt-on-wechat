# encoding:utf-8
"""reply_text reads non-JSON / error-less failure bodies without retrying, and Doubao works without args."""

import contextlib
import importlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PROVIDERS = [
    ("models.deepseek.deepseek_bot", "DeepSeekBot"),
    ("models.doubao.doubao_bot", "DoubaoBot"),
    ("models.moonshot.moonshot_bot", "MoonshotBot"),
]
CONF = {"temperature": 0.7, "top_p": 1.0, "request_timeout": 60,
        "deepseek_api_key": "k", "ark_api_key": "k", "moonshot_api_key": "k"}


@contextlib.contextmanager
def _bot(module_path, class_name):
    fake_conf = MagicMock()
    fake_conf.get.side_effect = lambda key, default=None: CONF.get(key, default)
    # api_key / base_url read conf() lazily, so keep it patched during the call.
    with patch(module_path + ".conf", return_value=fake_conf), \
            patch(module_path + ".SessionManager"), \
            patch(module_path + ".time", MagicMock()):
        yield getattr(importlib.import_module(module_path), class_name)()


def _session():
    return MagicMock(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.parametrize("module_path,class_name", PROVIDERS)
@pytest.mark.parametrize("json_side_effect", [ValueError("not json"), lambda: {"detail": "nope"}])
def test_error_body_without_error_object_is_not_retried(module_path, class_name, json_side_effect):
    response = MagicMock(status_code=401, text="<html>401</html>")
    response.json.side_effect = json_side_effect
    with _bot(module_path, class_name) as bot:
        with patch(module_path + ".requests.post", return_value=response) as post:
            result = bot.reply_text(_session(), args=dict(bot.args))
    assert post.call_count == 1
    assert result == {"completion_tokens": 0, "content": "授权失败，请检查API Key是否正确"}


def test_doubao_reply_text_without_args_uses_self_args():
    module_path = "models.doubao.doubao_bot"
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "choices": [{"message": {"content": "title"}}],
        "usage": {"total_tokens": 12, "completion_tokens": 6},
    }
    with _bot(module_path, "DoubaoBot") as bot:
        with patch(module_path + ".requests.post", return_value=response) as post:
            result = bot.reply_text(_session())
    assert result["content"] == "title"
    assert post.call_args.kwargs["json"]["model"] == bot.args["model"]
