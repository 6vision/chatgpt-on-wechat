"""create_default_embedding_provider degrades, not raises, on a non-string config value.

Same shape as test_reranker_config_shape.py: config.json is hand-editable, so a
JSON boolean or number can reach a `.strip()` call. Here it is worse than a lost
embedding provider -- the AttributeError propagates out of
AgentInitializer._setup_memory_system()'s single broad try/except, so the Agent
comes up with no memory manager and no memory tools at all.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from agent.memory.embedding.factory import create_default_embedding_provider  # noqa: E402

NON_STRINGS = [True, False, 0, 1, -1, 3.5, ["local"], {"provider": "local"},
               (1, 2), b"local"]

_OPENAI_DEFAULT_MODEL = "text-embedding-3-small"


class _FakeConf:
    """Stand-in for config.conf() backed by a plain dict."""

    def __init__(self, values):
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)


def _conf(values):
    """Patch config.conf so the factory reads our values instead of config.json."""
    return mock.patch.object(config, "conf", lambda: _FakeConf(values))


class TestEmbeddingFactoryToleratesNonStringConfig:
    def test_a_non_string_provider_does_not_raise(self):
        """A JSON bool/number must not take the whole memory system down."""
        for bad in NON_STRINGS:
            with _conf({"embedding_provider": bad}):
                # A non-string is treated as "not configured", which is the
                # documented path A: no keys are set here, so it resolves to None.
                assert create_default_embedding_provider() is None, bad

    def test_a_non_string_model_does_not_raise(self):
        for bad in NON_STRINGS:
            with _conf({
                "embedding_provider": "openai",
                "open_ai_api_key": "sk-test",
                "embedding_model": bad,
            }):
                create_default_embedding_provider()

    def test_a_non_string_api_base_does_not_raise(self):
        for bad in NON_STRINGS:
            with _conf({
                "embedding_provider": "openai",
                "open_ai_api_key": "sk-test",
                "open_ai_api_base": bad,
            }):
                create_default_embedding_provider()

    # ---- controls: string config keeps working ---------------------------

    def test_a_string_provider_is_still_normalised(self, monkeypatch):
        seen = {}

        def _fake_create(**kwargs):
            seen.update(kwargs)

            class _Provider:
                dimensions = 3

            return _Provider()

        monkeypatch.setattr(
            "agent.memory.embedding.provider.create_embedding_provider", _fake_create
        )
        with _conf({"embedding_provider": "  OPENAI  ", "open_ai_api_key": "sk-test"}):
            provider = create_default_embedding_provider()

        assert provider is not None
        assert seen["provider"] == "openai"
        assert seen["model"] == _OPENAI_DEFAULT_MODEL
        assert seen["api_key"] == "sk-test"

    def test_a_non_string_model_falls_back_to_the_default(self, monkeypatch):
        seen = {}

        def _fake_create(**kwargs):
            seen.update(kwargs)

            class _Provider:
                dimensions = 3

            return _Provider()

        monkeypatch.setattr(
            "agent.memory.embedding.provider.create_embedding_provider", _fake_create
        )
        with _conf({
            "embedding_provider": "openai",
            "open_ai_api_key": "sk-test",
            "embedding_model": 7,
        }):
            create_default_embedding_provider()

        assert seen["model"] == _OPENAI_DEFAULT_MODEL

    def test_a_non_string_api_base_falls_back_to_the_default(self, monkeypatch):
        seen = {}

        def _fake_create(**kwargs):
            seen.update(kwargs)

            class _Provider:
                dimensions = 3

            return _Provider()

        monkeypatch.setattr(
            "agent.memory.embedding.provider.create_embedding_provider", _fake_create
        )
        with _conf({
            "embedding_provider": "openai",
            "open_ai_api_key": "sk-test",
            "open_ai_api_base": 1,
        }):
            create_default_embedding_provider()

        assert seen["api_base"] == "https://api.openai.com/v1"
