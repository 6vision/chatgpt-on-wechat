# encoding:utf-8
"""Azure DALL-E must fall back to the *values* of the openai config keys.

``create_img`` resolved its endpoint and key as::

    endpoint = conf().get("azure_openai_dalle_api_base", "open_ai_api_base")
    api_key  = conf().get("azure_openai_dalle_api_key",  "open_ai_api_key")

``Config.get`` is ``get(key, default)`` -- the second argument is a default
*value*, not a sibling key to look up. So a user who left the optional
``azure_openai_dalle_*`` keys unset got the literal strings ``"open_ai_api_base"``
and ``"open_ai_api_key"``; the key went into the ``api-key`` header and the URL
became ``open_ai_api_base/openai/deployments/...``. The configured
``open_ai_api_key`` was never read by any code path, and the bare ``except
Exception`` reported it as a generic "Image generation failed".

config.py documents the intended behaviour ("defaults to open_ai_api_base"),
so the sibling key's value is what belongs here.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module
from config import Config

OPENAI_API_BASE = "https://relay.example.com/v1"
OPENAI_API_KEY = "sk-openai-fallback"
AZURE_API_BASE = "https://my-resource.openai.azure.com"
AZURE_API_KEY = "azure-dalle-key"


def _install_conf(monkeypatch, **overrides):
    """Install a Config as the global config, so the real config.json is never read."""
    cfg = {
        "bot_type": "azure",
        "open_ai_api_key": OPENAI_API_KEY,
        "open_ai_api_base": OPENAI_API_BASE,
    }
    cfg.update(overrides)
    monkeypatch.setattr(config_module, "config", Config(cfg))


def _bot():
    """An AzureChatGPTBot with no __init__ run: create_img needs no instance state."""
    from models.chatgpt.chat_gpt_bot import AzureChatGPTBot

    return AzureChatGPTBot.__new__(AzureChatGPTBot)


def _capture(monkeypatch):
    """Record the (url, headers) create_img would send, and answer the call."""
    seen = {}

    submission = type("Response", (), {})()
    submission.headers = {"operation-location": "https://poll.example.com/op/1"}
    submission.raise_for_status = lambda: None
    submission.json = lambda: {
        "status": "succeeded",
        "data": [{"url": "https://images.example.com/out.png"}],
        "result": {"data": [{"url": "https://images.example.com/out.png"}]},
    }

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs["headers"]
        return submission

    def fake_get(url, **kwargs):
        seen["poll_url"] = url
        seen["poll_headers"] = kwargs["headers"]
        return submission

    monkeypatch.setattr("models.chatgpt.chat_gpt_bot.requests.post", fake_post)
    monkeypatch.setattr("models.chatgpt.chat_gpt_bot.requests.get", fake_get)
    return seen


def test_dalle2_falls_back_to_the_openai_api_base_value(monkeypatch):
    _install_conf(monkeypatch, text_to_image="dall-e-2")
    seen = _capture(monkeypatch)

    assert _bot().create_img("a cat") == (True, "https://images.example.com/out.png")

    assert seen["url"] == (
        f"{OPENAI_API_BASE}/openai/images/generations:submit?api-version=2023-06-01-preview")
    assert seen["url"].startswith(OPENAI_API_BASE)
    assert seen["url"] != "open_ai_api_base/openai/images/generations:submit?api-version=2023-06-01-preview"


def test_dalle2_falls_back_to_the_openai_api_key_value(monkeypatch):
    _install_conf(monkeypatch, text_to_image="dall-e-2")
    seen = _capture(monkeypatch)

    _bot().create_img("a cat")

    assert seen["headers"]["api-key"] == OPENAI_API_KEY
    assert seen["headers"]["api-key"] != "open_ai_api_key"
    assert seen["poll_headers"]["api-key"] == OPENAI_API_KEY


def test_dalle3_falls_back_to_the_openai_api_base_value(monkeypatch):
    _install_conf(monkeypatch, text_to_image="dall-e-3")
    seen = _capture(monkeypatch)

    assert _bot().create_img("a cat") == (True, "https://images.example.com/out.png")

    assert seen["url"] == (
        f"{OPENAI_API_BASE}/openai/deployments/text_to_image/images/generations"
        "?api-version=2024-02-15-preview")
    assert seen["url"].startswith(OPENAI_API_BASE)
    assert seen["url"] != (
        "open_ai_api_base/openai/deployments/text_to_image/images/generations"
        "?api-version=2024-02-15-preview")


def test_dalle3_falls_back_to_the_openai_api_key_value(monkeypatch):
    _install_conf(monkeypatch, text_to_image="dall-e-3")
    seen = _capture(monkeypatch)

    _bot().create_img("a cat")

    assert seen["headers"]["api-key"] == OPENAI_API_KEY
    assert seen["headers"]["api-key"] != "open_ai_api_key"


@pytest.mark.parametrize("model", ["dall-e-2", "dall-e-3"])
def test_blank_azure_keys_fall_back_to_the_openai_values(monkeypatch, model):
    """An azure key left blank in config.json is as absent as a missing one."""
    _install_conf(monkeypatch, text_to_image=model,
                  azure_openai_dalle_api_base="", azure_openai_dalle_api_key="")
    seen = _capture(monkeypatch)

    _bot().create_img("a cat")

    assert seen["url"].startswith(OPENAI_API_BASE)
    assert seen["headers"]["api-key"] == OPENAI_API_KEY


@pytest.mark.parametrize("model", ["dall-e-2", "dall-e-3"])
def test_configured_azure_keys_still_win(monkeypatch, model):
    """The documented default only applies when the azure keys are unset."""
    _install_conf(monkeypatch, text_to_image=model,
                  azure_openai_dalle_api_base=AZURE_API_BASE,
                  azure_openai_dalle_api_key=AZURE_API_KEY)
    seen = _capture(monkeypatch)

    _bot().create_img("a cat")

    assert seen["url"].startswith(AZURE_API_BASE + "/")
    assert seen["headers"]["api-key"] == AZURE_API_KEY


def test_deployment_id_default_is_the_literal_name(monkeypatch):
    """`azure_openai_dalle_deployment_id` defaults to a deployment *name*.

    Unlike the two keys above, config.py documents this one as "defaults to
    text_to_image" -- an Azure deployment name, not a sibling config key -- so
    it is not a nested lookup and must not be changed into one.
    """
    _install_conf(monkeypatch, text_to_image="dall-e-3")
    seen = _capture(monkeypatch)

    _bot().create_img("a cat")

    assert "/openai/deployments/text_to_image/" in seen["url"]


def test_configured_deployment_id_is_used(monkeypatch):
    _install_conf(monkeypatch, text_to_image="dall-e-3",
                  azure_openai_dalle_deployment_id="my-dalle-deployment")
    seen = _capture(monkeypatch)

    _bot().create_img("a cat")

    assert "/openai/deployments/my-dalle-deployment/" in seen["url"]