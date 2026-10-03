# encoding:utf-8
"""
Regression tests for the search thresholds MemoryManager.search resolves.

`search` documents `max_results` / `min_score` as caller-supplied overrides and
resolves them with `x = x or self.config.x`, so an override of 0 — the value that
means "no threshold" and "return nothing" respectively — was indistinguishable
from "not supplied" and got silently replaced by the configured default. An Agent
asking `memory_search` for `min_score: 0` to see every weak match instead got the
0.1 default, so the low-scoring hits it specifically wanted were dropped with no
indication that a threshold had been applied.
"""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.manager import MemoryManager
from agent.memory.storage import SearchResult


def _result(label):
    """A distinct chunk per label, so every hit keeps its own rank position."""
    return SearchResult(
        path=f"memory/shared/{label}.md",
        start_line=1,
        end_line=1,
        score=0.5,
        snippet=f"snippet {label}",
        source="memory",
        user_id=None,
    )


def _manager(keyword_hits, max_results=10, min_score=0.4):
    # search() only reaches the config, the storage and the reranker hook, so a
    # bare instance avoids opening a real MemoryStorage/embedding provider.
    manager = MemoryManager.__new__(MemoryManager)
    manager.reranker = None
    manager.embedding_provider = None
    manager._dirty = False
    manager.config = SimpleNamespace(
        max_results=max_results,
        min_score=min_score,
        sync_on_search=False,
        vector_weight=0.7,
        keyword_weight=0.3,
    )
    manager.storage = SimpleNamespace(search_keyword=lambda **_: keyword_hits)
    return manager


class TestSearchHonoursExplicitThresholds(unittest.TestCase):
    """An override the caller passed is used verbatim, including when it is 0."""

    def test_zero_min_score_keeps_hits_below_the_configured_default(self):
        # Four keyword-only hits rank-normalize to 1.0 / 0.75 / 0.5 / 0.25, so
        # the configured 0.4 default cuts the last one. min_score=0 asks for
        # everything, and "everything" must include that hit.
        hits = [_result(label) for label in ("a", "b", "c", "d")]
        manager = _manager(hits)

        results = asyncio.run(manager.search("query", min_score=0.0))

        self.assertEqual(len(results), 4)
        self.assertIn("memory/shared/d.md", [r.path for r in results])

    def test_the_configured_default_still_applies_when_no_override_is_given(self):
        hits = [_result(label) for label in ("a", "b", "c", "d")]
        manager = _manager(hits)

        results = asyncio.run(manager.search("query"))

        self.assertEqual([r.path for r in results], [
            "memory/shared/a.md",
            "memory/shared/b.md",
            "memory/shared/c.md",
        ])

    def test_a_nonzero_override_still_wins_over_the_default(self):
        hits = [_result(label) for label in ("a", "b", "c", "d")]
        manager = _manager(hits)

        results = asyncio.run(manager.search("query", min_score=0.9))

        self.assertEqual([r.path for r in results], ["memory/shared/a.md"])

    def test_zero_max_results_returns_nothing(self):
        # The same falsy-zero read applies to the result cap: asking for zero
        # results must not be answered with the configured batch of ten.
        hits = [_result(label) for label in ("a", "b", "c", "d")]
        manager = _manager(hits)

        results = asyncio.run(manager.search("query", max_results=0))

        self.assertEqual(results, [])

    def test_the_configured_cap_still_applies_when_no_override_is_given(self):
        hits = [_result(label) for label in ("a", "b", "c", "d")]
        manager = _manager(hits, max_results=2)

        results = asyncio.run(manager.search("query"))

        self.assertEqual([r.path for r in results], [
            "memory/shared/a.md",
            "memory/shared/b.md",
        ])


if __name__ == "__main__":
    unittest.main()
