"""Keyword-only memory retrieval must not discard ordinary Unicode words."""

import asyncio

import pytest

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from agent.memory.storage import MemoryChunk


@pytest.mark.parametrize("query", ["καλημέρα", "договор", "مرحبا", "été", "invoice", "中文教程"])
@pytest.mark.parametrize("fts_available", [True, False])
def test_keyword_only_manager_finds_unicode_memory(tmp_path, query, fts_available):
    manager = MemoryManager(MemoryConfig(workspace_root=str(tmp_path), sync_on_search=False))
    try:
        if fts_available and not manager.storage.fts5_available:
            pytest.skip("SQLite has no FTS5")
        if not fts_available:
            manager.storage.fts5_available = False
            manager.storage.trigram_fts5_available = False
        manager.storage.save_chunk(MemoryChunk(
            id="note", user_id=None, scope="shared", source="memory", path="memory/note.md",
            start_line=1, end_line=1, text=f"{query}: details to remember", embedding=None, hash="note-hash",
        ))
        results = asyncio.run(manager.search(query))
        assert [result.path for result in results] == ["memory/note.md"]
        assert asyncio.run(manager.search("unrelatedword")) == []
    finally:
        manager.storage.close()


def test_trigram_query_keeps_unicode_term_next_to_cjk(tmp_path):
    manager = MemoryManager(MemoryConfig(workspace_root=str(tmp_path), sync_on_search=False))
    try:
        if not manager.storage.trigram_fts5_available:
            pytest.skip("SQLite has no trigram FTS5")
        for name, text in [("match", "中文教程 договор"), ("decoy", "中文教程 unrelated")]:
            manager.storage.save_chunk(MemoryChunk(
                id=name, user_id=None, scope="shared", source="memory", path=f"memory/{name}.md",
                start_line=1, end_line=1, text=text, embedding=None, hash=name,
            ))
        results = asyncio.run(manager.search("中文教程 договор"))
        assert [result.path for result in results] == ["memory/match.md"]
    finally:
        manager.storage.close()
