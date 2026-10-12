"""Chunk ids must stay unique for the pieces of one over-long line.

A line longer than the chunk budget is hard-split into several pieces that all
share the same (start_line, end_line). save_chunks_batch UPSERTs
ON CONFLICT(id) DO UPDATE, so if those pieces share a chunk id as well, every
piece but one is silently overwritten and its text never reaches the index.

The index-level tests drive MemoryManager.add_memory() — the production entry
point that indexes dynamic memory — so they fail with the loss itself rather
than with an incidental AttributeError on older revisions.
"""

import asyncio
import hashlib
import tempfile
from pathlib import Path

from agent.memory.chunker import TextChunker
from agent.memory.manager import MemoryManager
from agent.memory.storage import MemoryStorage

LONG_LINE = "A" * 950
BUDGET_CHARS = 200  # TextChunker(max_tokens=50) -> 50 * 4 chars


def _chunker():
    return TextChunker(max_tokens=50, overlap_tokens=5)


def _split_pieces():
    """The pieces chunk_text() cuts LONG_LINE into."""
    chunks = _chunker().chunk_text(LONG_LINE)
    assert len(chunks) > 1, "LONG_LINE must exceed the budget to be split"
    return chunks


def _throwaway_manager():
    """A MemoryManager wired to a temp index, with embeddings switched off."""
    manager = MemoryManager.__new__(MemoryManager)
    manager.chunker = _chunker()
    manager.embedding_provider = None  # no network calls
    tmp = Path(tempfile.mkdtemp())
    manager.storage = MemoryStorage(tmp / "index.db")
    manager.workspace_dir = tmp
    return manager


def _index(manager, content=LONG_LINE, path="notes.md"):
    asyncio.run(manager.add_memory(content, path=path))
    return manager.storage.conn.execute(
        "SELECT id, text FROM chunks WHERE path = ?", (path,)
    ).fetchall()


def test_no_text_is_lost_when_an_over_long_line_is_indexed():
    rows = _index(_throwaway_manager())
    stored = "".join(row[1] for row in rows)
    assert stored == LONG_LINE


def test_every_piece_of_an_over_long_line_gets_its_own_row():
    pieces = _split_pieces()
    rows = _index(_throwaway_manager())
    assert len(rows) == len(pieces)


def test_ordinary_chunks_keep_the_historical_chunk_id():
    """A chunk that was never hard-split must keep its pre-existing id."""
    expected = hashlib.md5(b"notes.md:1:3").hexdigest()
    manager = MemoryManager.__new__(MemoryManager)
    assert manager._generate_chunk_id("notes.md", 1, 3) == expected


def test_short_lines_are_untouched():
    """No over-long line -> chunks are unchanged and nothing collides."""
    manager = _throwaway_manager()
    rows = _index(manager, content="one\ntwo\nthree", path="short.md")
    assert len(rows) == 1
    assert rows[0][1] == "one\ntwo\nthree"
