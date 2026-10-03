# encoding:utf-8
"""Azure DALL-E falls back to the values of open_ai_api_base / open_ai_api_key."""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module
from config import Config

OPENAI_BASE = "https://relay.example.com/v1"
OPENAI_KEY = "sk-openai-fallback"


def _create_img(monkeypatch, **overrides):
    cfg = {"bot_type": "azure", "open_ai_api_base": OPENAI_BASE, "open_ai_api_key": OPENAI_KEY}
    monkeypatch.setattr(config_module, "config", Config({**cfg, **overrides}))
    response = MagicMock(headers={"operation-location": "https://poll.example.com/op/1"})
    response.json.return_value = {"status": "succeeded", "data": [{"url": "https://img/out.png"}],
                                  "result": {"data": [{"url": "https://img/out.png"}]}}
    post = MagicMock(return_value=response)
    monkeypatch.setattr("models.chatgpt.chat_gpt_bot.requests.post", post)
    monkeypatch.setattr("models.chatgpt.chat_gpt_bot.requests.get", MagicMock(return_value=response))
    from models.chatgpt.chat_gpt_bot import AzureChatGPTBot
    assert AzureChatGPTBot.__new__(AzureChatGPTBot).create_img("a cat") == (True, "https://img/out.png")
    return post.call_args.args[0], post.call_args.kwargs["headers"]["api-key"]


@pytest.mark.parametrize("model", ["dall-e-2", "dall-e-3"])
@pytest.mark.parametrize("azure_value", [None, ""])
def test_unset_azure_keys_fall_back_to_openai_values(monkeypatch, model, azure_value):
    overrides = {"text_to_image": model}
    if azure_value is not None:
        overrides.update(azure_openai_dalle_api_base=azure_value, azure_openai_dalle_api_key=azure_value)
    url, api_key = _create_img(monkeypatch, **overrides)
    assert url.startswith(OPENAI_BASE + "/openai/")
    assert api_key == OPENAI_KEY


def test_configured_azure_keys_still_win(monkeypatch):
    url, api_key = _create_img(monkeypatch, text_to_image="dall-e-3",
                               azure_openai_dalle_api_base="https://res.openai.azure.com",
                               azure_openai_dalle_api_key="azure-key")
    assert url.startswith("https://res.openai.azure.com/openai/")
    assert api_key == "azure-key"
