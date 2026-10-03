# encoding:utf-8
"""
Regression tests for the LIKE fallback of MemoryStorage.search_keyword.

search_keyword documents a three-step strategy whose last step is "If FTS5 fails
OR returns empty for non-CJK, also try LIKE so a broken FTS5 shadow table doesn't
silently kill keyword search". The LIKE step was in fact gated on
`not fts5_available or _contains_cjk(query)`, so a state the storage explicitly
supports — FTS5 present but the trigram table unavailable — combined with a
`chunks_fts` shadow table that answers nothing, made a plain ASCII query return
an empty list. The text was sitting in `chunks` all along, so `memory_search`
told the agent "No memories found" for a term it could have matched.
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.storage import MemoryChunk, MemoryStorage


def _wait_for_maintenance():
    """Storage opens a background thread that may repair the search indexes.
    Let it finish before a test breaks the index on purpose, so the two do not
    race over the same table."""
    deadline = time.time() + 10
    while time.time() < deadline:
        threads = [t for t in threading.enumerate() if t.name == "memory-db-maintenance"]
        if not threads:
            return
        for t in threads:
            t.join(timeout=10)
        time.sleep(0.05)


class TestSearchKeywordLikeFallback(unittest.TestCase):
    """A keyword query whose FTS stage comes back empty must still be answered
    from the LIKE scan instead of reporting that nothing matched."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.storage = MemoryStorage(self.tmp / "index.db")
        _wait_for_maintenance()
        self.storage.save_chunk(MemoryChunk(
            id="c1", user_id=None, scope="shared", source="memory",
            path="memory/shared/finance.md", start_line=1, end_line=1,
            text="The invoice for March was paid by the client.",
            embedding=None, hash="h1",
        ))
        self.storage.conn.commit()

    def tearDown(self):
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers -------------------------------------------------------

    def _damage_fts_index(self):
        """Drop the shadow table, as an interrupted rebuild or a corrupted
        index would leave it: every MATCH against it now raises, and
        _search_fts5 answers with an empty list."""
        self.storage.conn.execute("DROP TABLE IF EXISTS chunks_fts")
        self.storage.conn.commit()

    def _disable_trigram(self):
        """The state _init_db falls back to when the trigram table cannot be
        created: FTS5 works, trigram does not."""
        self.storage.trigram_fts5_available = False

    def _spy_on_like(self):
        """Record the queries handed to the LIKE path."""
        queries = []
        real = self.storage._search_like

        def spy(query, *args, **kwargs):
            queries.append(query)
            return real(query, *args, **kwargs)

        self.storage._search_like = spy
        return queries

    # -- tests ---------------------------------------------------------

    def test_ascii_query_falls_back_to_like_when_fts_index_is_damaged(self):
        # This is the reported state: FTS5 available, trigram unavailable, and
        # a damaged chunks_fts that finds nothing for a pure-ASCII query.
        self._disable_trigram()
        self._damage_fts_index()

        results = self.storage.search_keyword("invoice")

        self.assertEqual([r.path for r in results], ["memory/shared/finance.md"])
        self.assertIn("invoice", results[0].snippet.lower())

    def test_the_like_path_supplies_those_results(self):
        # Not merely a non-empty answer: it must be the LIKE scan that ran,
        # since the FTS stage demonstrably had nothing to offer.
        self._disable_trigram()
        self._damage_fts_index()
        like_queries = self._spy_on_like()

        results = self.storage.search_keyword("invoice")

        self.assertEqual(like_queries, ["invoice"])
        self.assertTrue(results)

    def test_a_damaged_index_still_answers_queries_with_no_fts_tokens(self):
        # _build_fts_query yields nothing for a query that has no ASCII token
        # (punctuation only), so no FTS stage runs at all. That is not a broken
        # index, but it is not a reason to skip LIKE either.
        self._disable_trigram()
        self._damage_fts_index()

        results = self.storage.search_keyword("***")

        # Nothing to match on either way — the guard is that this stays empty
        # rather than raising, and that a real term is still reachable.
        self.assertEqual(results, [])
        self.assertTrue(self.storage.search_keyword("March"))

    def test_healthy_index_answers_without_scanning_like(self):
        # The fallback must stay a last resort: when FTS5 already answered,
        # LIKE is not consulted.
        self._disable_trigram()
        like_queries = self._spy_on_like()

        results = self.storage.search_keyword("invoice")

        self.assertTrue(results)
        self.assertEqual(like_queries, [])

    def test_cjk_query_still_falls_back_to_like_without_trigram(self):
        # Pre-existing behaviour that the gate already covered: a CJK query
        # with no trigram index goes straight to LIKE.
        self._disable_trigram()

        results = self.storage.search_keyword("发票")

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
