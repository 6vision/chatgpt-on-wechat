# encoding:utf-8
"""search_keyword falls back to LIKE when an FTS5 stage ran and found nothing."""
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.storage import MemoryChunk, MemoryStorage


@pytest.fixture
def storage(tmp_path):
    s = MemoryStorage(tmp_path / "index.db")
    # Let the background index repair finish before the test breaks the index.
    for t in threading.enumerate():
        if t.name == "memory-db-maintenance":
            t.join(timeout=10)
    s.save_chunk(MemoryChunk(
        id="c1", user_id=None, scope="shared", source="memory",
        path="memory/shared/finance.md", start_line=1, end_line=1,
        text="The invoice for March was paid by the client.",
        embedding=None, hash="h1",
    ))
    s.conn.commit()
    s.trigram_fts5_available = False
    yield s
    s.close()


def test_ascii_query_uses_like_when_fts_index_is_broken(storage):
    storage.conn.execute("DROP TABLE IF EXISTS chunks_fts")
    storage.conn.commit()

    results = storage.search_keyword("invoice")

    assert [r.path for r in results] == ["memory/shared/finance.md"]
