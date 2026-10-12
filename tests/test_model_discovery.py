# encoding:utf-8
"""Provider model discovery: GET /models -> editable catalog rows."""

import json

from channel.web.api import models as models_api
from channel.web.core.providers import PROVIDER_MODELS


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def test_discover_openai_compatible_models(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None, proxies=None):
        captured.update(url=url, headers=headers, params=params, timeout=timeout)
        return _Response({"data": [{"id": "model-a"}, {"id": "model-b"}, {"id": "model-a"}]})

    monkeypatch.setattr(models_api.requests, "get", fake_get)

    models = models_api._discover_models(
        "openai", api_key="sk-test", api_base="https://api.example.com/v1"
    )

    assert [m["name"] for m in models] == ["model-a", "model-b"]
    assert models[0]["capabilities"] == ["text"]
    assert captured["url"] == "https://api.example.com/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["timeout"] == 10


def test_discover_claude_uses_x_api_key_and_version(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None, proxies=None):
        captured.update(url=url, headers=headers)
        return _Response({"data": [{"id": "claude-sonnet-5"}]})

    monkeypatch.setattr(models_api.requests, "get", fake_get)

    models = models_api._discover_models(
        "claudeAPI", api_key="sk-ant", api_base="https://api.anthropic.com/v1"
    )

    assert [m["name"] for m in models] == ["claude-sonnet-5"]
    assert captured["url"] == "https://api.anthropic.com/v1/models"
    assert captured["headers"]["x-api-key"] == "sk-ant"
    assert captured["headers"]["anthropic-version"]


def test_discover_gemini_uses_query_key_and_strips_models_prefix(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None, proxies=None):
        captured.update(url=url, headers=headers, params=params)
        return _Response({"models": [
            {"name": "models/gemini-2.5-pro"},
            {"name": "models/gemini-2.5-flash"},
        ]})

    monkeypatch.setattr(models_api.requests, "get", fake_get)

    models = models_api._discover_models(
        "gemini", api_key="gm-key", api_base="https://generativelanguage.googleapis.com"
    )

    assert [m["name"] for m in models] == ["gemini-2.5-pro", "gemini-2.5-flash"]
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/models"
    assert captured["params"] == {"key": "gm-key"}


def test_discovery_surfaces_upstream_errors_without_leaking_the_key(monkeypatch):
    monkeypatch.setattr(
        models_api.requests,
        "get",
        lambda *a, **k: _Response({"error": {"message": "bad key sk-secret"}}, status_code=401),
    )

    try:
        models_api._discover_models("openai", api_key="sk-secret", api_base="https://api.example.com/v1")
    except models_api.ModelDiscoveryError as exc:
        assert "401" in str(exc)
        assert "sk-secret" not in str(exc)
    else:
        raise AssertionError("expected ModelDiscoveryError")


def test_handler_uses_saved_key_when_the_ui_sends_a_masked_sentinel(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        models_api,
        "conf",
        lambda: {"open_ai_api_key": "stored-secret", "open_ai_api_base": "https://api.example.com/v1"},
    )
    monkeypatch.setattr(
        models_api,
        "_discover_models",
        lambda provider_id, api_key, api_base: seen.update(
            provider_id=provider_id, api_key=api_key, api_base=api_base
        ) or [{"name": "discovered-model", "capabilities": ["text"]}],
    )

    payload = json.loads(models_api.ModelsHandler()._handle_discover_models({
        "provider_id": "openai",
        "api_key": "stor********cret",
    }))

    assert payload["status"] == "success"
    assert payload["models"] == [{"name": "discovered-model", "capabilities": ["text"]}]
    assert seen == {
        "provider_id": "openai",
        "api_key": "stored-secret",
        "api_base": "https://api.example.com/v1",
    }


def test_handler_never_sends_the_saved_key_to_another_base(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        models_api,
        "conf",
        lambda: {"open_ai_api_key": "stored-secret", "open_ai_api_base": "https://api.example.com/v1"},
    )
    monkeypatch.setattr(
        models_api,
        "_discover_models",
        lambda provider_id, api_key, api_base: seen.update(api_key=api_key) or [{"name": "m"}],
    )

    payload = json.loads(models_api.ModelsHandler()._handle_discover_models({
        "provider_id": "openai",
        "api_key": "stor********cret",
        "api_base": "https://collector.invalid/v1",
    }))

    assert payload["status"] == "error"
    assert seen == {}


def test_discovered_models_get_a_capability_guess():
    guess = models_api._discovered_capabilities
    assert guess("gpt-4o") == ["text"]
    assert guess("text-embedding-3-small") == ["embedding"]
    assert guess("tts-1") == ["tts"]
    assert guess("whisper-1") == ["asr"]
    assert guess("mimo-v2.5-asr") == ["asr"]
    assert guess("doubao-seedance-2-0") == ["video"]
    assert guess("kling-video-o1") == ["video"]
    assert guess("doubao-seedream-5-0-pro") == ["image"]
    assert guess("qwen-vl-max") == ["text", "vision"]


def test_structured_modalities_and_budgets_win_over_the_name(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None, proxies=None):
        return _Response({"data": [{
            "id": "deepseek-flash",
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
            "context_window": 1048576,
            "max_output_tokens": 393216,
        }, {
            "id": "gpt-realtime-preview",
        }, {
            "id": "seedance-from-type",
            "model_type": "VIDEO",
        }, {
            "id": "jev-latest",
            "model_type": "JUDGE",
        }]})

    monkeypatch.setattr(models_api.requests, "get", fake_get)
    models = models_api._discover_models(
        "openai", api_key="sk-test", api_base="https://api.example.com/v1"
    )
    by_name = {m["name"]: m for m in models}
    assert "gpt-realtime-preview" not in by_name
    assert by_name["deepseek-flash"]["capabilities"] == ["text", "vision"]
    assert by_name["deepseek-flash"]["context_window"] == 1048576
    assert by_name["deepseek-flash"]["max_output_tokens"] == 393216
    assert by_name["seedance-from-type"]["capabilities"] == ["video"]
    assert "jev-latest" not in by_name


def test_linkai_dashscope_minimax_have_a_discoverable_default_base():
    assert PROVIDER_MODELS["linkai"]["api_base_default"].endswith("/v1")
    assert "compatible-mode" in PROVIDER_MODELS["dashscope"]["api_base_default"]
    assert PROVIDER_MODELS["minimax"]["api_base_default"].endswith("/v1")
    assert models_api._models_endpoint("linkai", "https://api.link-ai.tech") == (
        "https://api.link-ai.tech/v1/models"
    )
    assert models_api._models_endpoint("linkai", "https://api.link-ai.tech/v1") == (
        "https://api.link-ai.tech/v1/models"
    )


def test_handler_uses_linkai_default_base(monkeypatch):
    seen = {}
    monkeypatch.setattr(models_api, "conf", lambda: {"linkai_api_key": "link-secret"})
    monkeypatch.setattr(
        models_api,
        "_discover_models",
        lambda provider_id, api_key, api_base: seen.update(
            provider_id=provider_id, api_key=api_key, api_base=api_base
        ) or [{"name": "gpt-6-luna", "capabilities": ["text"]}],
    )

    payload = json.loads(models_api.ModelsHandler()._handle_discover_models({
        "provider_id": "linkai",
        "api_key": "link********cret",
    }))

    assert payload["status"] == "success"
    assert seen["provider_id"] == "linkai"
    assert seen["api_key"] == "link-secret"
    assert seen["api_base"] == "https://api.link-ai.tech/v1"
