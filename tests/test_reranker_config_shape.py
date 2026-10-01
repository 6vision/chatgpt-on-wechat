"""create_reranker disables reranking, not raises, on a non-string config value."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory import reranker  # noqa: E402

NON_STRINGS = [True, False, 0, 1, -1, 3.5, ["local"], {"provider": "local"},
               (1, 2), b"local"]


class TestCreateRerankerToleratesNonStringConfig:
    def test_a_non_string_provider_disables_reranking(self):
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
        out = reranker.create_reranker("local", None)
        assert out is not None
        assert type(out).__name__ == "SentenceTransformerReranker"

    def test_a_real_provider_is_still_normalised(self):
        out = reranker.create_reranker("  LOCAL  ")
        assert out is not None
        assert reranker.create_reranker("local") is out
