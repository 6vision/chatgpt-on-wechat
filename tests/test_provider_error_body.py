# encoding:utf-8
"""A refused reply_text call is answered, not re-sent: a non-JSON or
error-less failure body must not raise, and Doubao must accept missing args."""

import contextlib
import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# module path, class name, log tag
PROVIDERS = (
    ("models.deepseek.deepseek_bot", "DeepSeekBot"),
    ("models.doubao.doubao_bot", "DoubaoBot"),
    ("models.moonshot.moonshot_bot", "MoonshotBot"),
)

CONF_VALUES = {
    "model": None,
    "temperature": 0.7,
    "top_p": 1.0,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "clear_memory_commands": ["#清除记忆"],
    "conversation_max_tokens": 1000,
    "expires_in_seconds": 3600,
    "request_timeout": 60,
    "deepseek_api_key": "test-deepseek-key",
    "deepseek_api_base": "https://api.deepseek.com/v1",
    "ark_api_key": "test-ark-key",
    "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "moonshot_api_key": "test-moonshot-key",
    "moonshot_base_url": "https://api.moonshot.cn/v1",
}

GOOD_BODY = {
    "choices": [{"message": {"content": "会话标题"}}],
    "usage": {"total_tokens": 12, "completion_tokens": 6},
}


@contextlib.contextmanager
def _bot(module_path, class_name):
    """Build the provider's bot against a fake config, and keep it faked.

    ``api_key`` and ``base_url`` are properties that read ``conf()`` when
    ``reply_text`` runs, so the patch has to stay up for the whole call.
    """
    fake_conf = MagicMock()
    fake_conf.get.side_effect = lambda key, default=None: CONF_VALUES.get(key, default)

    with patch(module_path + ".conf", return_value=fake_conf):
        with patch(module_path + ".SessionManager"):
            module = importlib.import_module(module_path)
            bot = getattr(module, class_name)()
        # `time.sleep(3)` sits in the retry path this module is being asked
        # about; the retries themselves are what the assertions count.
        with patch(module_path + ".time", MagicMock()):
            yield module, bot


def _reply(status_code, text, json_body=None, not_json=False):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if not_json:
        response.json.side_effect = ValueError("Expecting value: line 1 column 1")
    else:
        response.json.return_value = json_body
    return response


def _session():
    session = MagicMock()
    session.messages = [{"role": "user", "content": "写一个短标题"}]
    return session


class TestProviderErrorBody(unittest.TestCase):
    """One HTTP call per refusal, with the wording the branch exists to give."""

    def test_non_json_error_body_is_read_once(self):
        # A gateway answers the refusal with HTML, so `res.json()` raises.
        for module_path, class_name in PROVIDERS:
            with self.subTest(provider=class_name):
                response = _reply(
                    401,
                    "<html><head><title>401 Authorization Required</title></head></html>",
                    not_json=True,
                )
                with _bot(module_path, class_name) as (module, bot):
                    with patch(module_path + ".requests.post", return_value=response) as post:
                        result = bot.reply_text(_session(), args=dict(bot.args))

                self.assertEqual(post.call_count, 1, "the refused request was re-sent")
                self.assertEqual(result["completion_tokens"], 0)
                self.assertEqual(result["content"], "授权失败，请检查API Key是否正确")

    def test_json_error_body_without_error_key_is_read_once(self):
        # FastAPI-style envelope: valid JSON, no `error` key.
        module_path, class_name = "models.moonshot.moonshot_bot", "MoonshotBot"
        body = {"detail": "model not found"}
        response = _reply(400, '{"detail": "model not found"}', json_body=body)

        with _bot(module_path, class_name) as (module, bot):
            with patch(module_path + ".requests.post", return_value=response) as post:
                result = bot.reply_text(_session(), args=dict(bot.args))

        self.assertEqual(post.call_count, 1, "the refused request was re-sent")
        self.assertEqual(result["completion_tokens"], 0)
        self.assertEqual(result["content"], "提问太快啦，请休息一下再问我吧")

    def test_a_successful_call_still_parses(self):
        for module_path, class_name in PROVIDERS:
            with self.subTest(provider=class_name):
                response = _reply(200, "", json_body=GOOD_BODY)
                with _bot(module_path, class_name) as (module, bot):
                    with patch(module_path + ".requests.post", return_value=response) as post:
                        result = bot.reply_text(_session(), args=dict(bot.args))

                self.assertEqual(post.call_count, 1)
                self.assertEqual(result["content"], "会话标题")
                self.assertEqual(result["completion_tokens"], 6)


class TestDoubaoReplyTextWithoutArgs(unittest.TestCase):
    """`session_service` calls `bot.reply_text(session)` with no args."""

    MODULE = "models.doubao.doubao_bot"

    def test_called_without_args_still_reaches_the_api(self):
        response = _reply(200, "", json_body=GOOD_BODY)

        with _bot(self.MODULE, "DoubaoBot") as (module, bot):
            with patch(self.MODULE + ".requests.post", return_value=response) as post:
                # The call `generate_session_title` / `optimize_prompt` make.
                result = bot.reply_text(_session())

        self.assertEqual(post.call_count, 1, "no request was made at all")
        self.assertEqual(result["content"], "会话标题")
        self.assertEqual(result["completion_tokens"], 6)

    def test_called_without_args_still_uses_self_args(self):
        response = _reply(200, "", json_body=GOOD_BODY)

        with _bot(self.MODULE, "DoubaoBot") as (module, bot):
            with patch(self.MODULE + ".requests.post", return_value=response) as post:
                bot.reply_text(_session())

        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], bot.args["model"])
        self.assertEqual(body["temperature"], bot.args["temperature"])


if __name__ == "__main__":
    unittest.main()
