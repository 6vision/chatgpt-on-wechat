"""create_default_embedding_provider treats non-string config values as unset instead of raising."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from agent.memory.embedding.factory import create_default_embedding_provider  # noqa: E402


def _build(monkeypatch, values):
    seen = {}

    def fake_create(**kwargs):
        seen.update(kwargs)
        return mock.Mock(dimensions=3)

    monkeypatch.setattr("agent.memory.embedding.provider.create_embedding_provider", fake_create)
    monkeypatch.delenv("LINKAI_API_KEY", raising=False)
    with mock.patch.object(config, "conf", lambda: dict(values)):
        return create_default_embedding_provider(), seen


@pytest.mark.parametrize("bad", [True, 1])
def test_non_string_provider_is_unset(monkeypatch, bad):
    provider, seen = _build(monkeypatch, {"embedding_provider": bad})
    assert provider is None and seen == {}


@pytest.mark.parametrize("key,field,default", [
    ("embedding_model", "model", "text-embedding-3-small"),
    ("open_ai_api_base", "api_base", "https://api.openai.com/v1"),
])
def test_non_string_value_falls_back_to_default(monkeypatch, key, field, default):
    _, seen = _build(monkeypatch, {"embedding_provider": "openai", "open_ai_api_key": "sk-test", key: 7})
    assert seen[field] == default


def test_string_provider_is_still_normalised(monkeypatch):
    _, seen = _build(monkeypatch, {"embedding_provider": "  OPENAI  ", "open_ai_api_key": "sk-test"})
    assert seen["provider"] == "openai"
