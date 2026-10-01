"""Regression: create_reranker must disable reranking, not raise, when the
config value is not a string.

config.json is hand-editable, so "rerank_provider": true or 1 is reachable.
The AttributeError that resulted escaped into
AgentInitializer._setup_memory_system(), whose one broad except turned it into
"Memory system not available" - so a bad rerank setting took down ALL of memory
search, not just reranking.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory import reranker  # noqa: E402

NON_STRINGS = [True, False, 0, 1, -1, 3.5, ["local"], {"provider": "local"},
               (1, 2), b"local"]


class TestCreateRerankerToleratesNonStringConfig:
    def test_a_non_string_provider_disables_reranking(self):
        # Before the fix each of these raised
        # AttributeError: 'bool' object has no attribute 'strip'
        for bad in NON_STRINGS:
            assert reranker.create_reranker(bad) is None, bad

    def test_a_non_string_model_does_not_raise(self):
        for bad in NON_STRINGS:
            out = reranker.create_reranker("nosuchprovider", bad)
            assert out is None, bad

    def test_an_unknown_provider_still_disables_reranking(self):
        assert reranker.create_reranker("nosuchprovider") is None

    def test_an_empty_provider_still_disables_reranking(self):
        assert reranker.create_reranker("") is None
        assert reranker.create_reranker(None) is None

    def test_a_non_string_model_still_builds_the_default_model(self):
        # The model name is only a factory argument; a junk value must fall back
        # to the provider default rather than blowing up agent init.
        out = reranker.create_reranker("local", None)
        assert out is not None
        assert type(out).__name__ == "SentenceTransformerReranker"

    def test_a_real_provider_is_still_normalised(self):
        # Whitespace and case are trimmed, exactly as before.
        out = reranker.create_reranker("  LOCAL  ")
        assert out is not None
        # The shared-instance cache is keyed on the normalised name.
        assert reranker.create_reranker("local") is out
