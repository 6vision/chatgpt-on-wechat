"""Owned Write → dirty sync → actual SQLite → public MemorySearch controls."""
import asyncio
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from agent.memory.embedding.provider import OpenAIEmbeddingProvider
from agent.tools.write.write import Write
from agent.tools.memory.memory_search import MemorySearchTool


@pytest.mark.parametrize("replacement", ["", " \t\n\n"])
def test_clearing_a_note_removes_its_searchable_content(tmp_path, replacement):
    workspace = tmp_path / "workspace"
    (workspace / "knowledge").mkdir(parents=True)
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(workspace)))
    writer = Write(config={"cwd": str(workspace), "memory_manager": manager})
    search = MemorySearchTool(manager)
    try:
        assert writer.execute({"path": "memory/owned.md", "content": "# Note\nQUARTZCLEAR8812 old fact\n"}).status == "success"
        assert writer.execute({"path": "memory/keep.md", "content": "# Keep\nTOPAZKEEP9913 retained fact\n"}).status == "success"
        before = search.execute({"query": "QUARTZCLEAR8812", "min_score": 0})
        assert before.status == "success"
        assert "QUARTZCLEAR8812" in str(before.result), before
        assert writer.execute({"path": "memory/owned.md", "content": replacement}).status == "success"
        after = search.execute({"query": "QUARTZCLEAR8812", "min_score": 0})
        assert after.status == "success"
        assert "old fact" not in str(after.result), after
        assert manager.storage.get_file_hash("memory/owned.md") == manager.storage.compute_hash(replacement)
        assert "TOPAZKEEP9913" in str(search.execute({"query": "TOPAZKEEP9913", "min_score": 0}).result)
        assert writer.execute({"path": "memory/owned.md", "content": "# New\nAMBERNEW5514 new fact\n"}).status == "success"
        assert "AMBERNEW5514" in str(search.execute({"query": "AMBERNEW5514", "min_score": 0}).result)
        assert "old fact" not in str(search.execute({"query": "QUARTZCLEAR8812", "min_score": 0}).result)
    finally:
        manager.storage.close()


@contextmanager
def _owned_embedding_endpoint():
    calls = []
    state = {"status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(payload)
            texts = payload["input"]
            texts = [texts] if isinstance(texts, str) else texts
            body = json.dumps({"data": [
                {"index": i, "embedding": [1.0, 0.0]} for i in range(len(texts))
            ]}).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = OpenAIEmbeddingProvider(
            model="owned-model", api_key="owned-fixture-key", dimensions=2,
            api_base="http://127.0.0.1:" + str(server.server_port) + "/v1",
        )
        yield provider, calls, state
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_empty_update_needs_no_embedding_request(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "knowledge").mkdir(parents=True)
    with _owned_embedding_endpoint() as (provider, calls, state):
        manager = MemoryManager(
            config=MemoryConfig(workspace_root=str(workspace)), embedding_provider=provider,
        )
        writer = Write(config={"cwd": str(workspace), "memory_manager": manager})
        try:
            assert writer.execute({"path": "memory/note.md", "content": "OLDAMBER3381 fact"}).status == "success"
            asyncio.run(manager.sync())
            assert calls
            initial_count = len(calls)
            assert writer.execute({"path": "memory/note.md", "content": ""}).status == "success"
            asyncio.run(manager.sync())
            assert len(calls) == initial_count
            assert manager.storage.get_file_hash("memory/note.md") == manager.storage.compute_hash("")
            assert manager.storage.search_keyword("OLDAMBER3381") == []
            assert manager.storage.conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE path = ?", ("memory/note.md",),
            ).fetchone()[0] == 0
        finally:
            manager.storage.close()


def test_embedding_failure_preserves_pending_empty_and_nonempty_entries(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "knowledge").mkdir(parents=True)
    with _owned_embedding_endpoint() as (provider, calls, state):
        manager = MemoryManager(
            config=MemoryConfig(workspace_root=str(workspace)), embedding_provider=provider,
        )
        writer = Write(config={"cwd": str(workspace), "memory_manager": manager})
        try:
            for path, text in [("memory/clear.md", "QUARTZOLD3341 old fact"),
                               ("memory/change.md", "TOPAZOLD2291 kept until success")]:
                assert writer.execute({"path": path, "content": text}).status == "success"
            asyncio.run(manager.sync())
            old_hash = manager.storage.get_file_hash("memory/clear.md")
            assert writer.execute({"path": "memory/clear.md", "content": ""}).status == "success"
            assert writer.execute({"path": "memory/change.md", "content": "TOPAZNEW2291 replacement"}).status == "success"
            state["status"] = 500
            asyncio.run(manager.sync())
            assert manager._dirty is True
            assert manager.storage.get_file_hash("memory/clear.md") == old_hash
            assert manager.storage.search_keyword("QUARTZOLD3341")
            assert manager.storage.search_keyword("TOPAZOLD2291")
            assert manager.storage.search_keyword("TOPAZNEW2291") == []
            state["status"] = 200
            asyncio.run(manager.sync())
            assert manager._dirty is False
            assert manager.storage.search_keyword("QUARTZOLD3341") == []
            assert manager.storage.search_keyword("TOPAZNEW2291")
            assert all(text.strip() for call in calls for text in call["input"])
        finally:
            manager.storage.close()


def test_never_indexed_blank_note_does_not_add_file_metadata(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "knowledge").mkdir(parents=True)
    manager = MemoryManager(config=MemoryConfig(workspace_root=str(workspace)))
    writer = Write(config={"cwd": str(workspace), "memory_manager": manager})
    try:
        assert writer.execute({"path": "memory/blank.md", "content": " \t\n"}).status == "success"
        assert writer.execute({"path": "memory/keep.md", "content": "TOPAZKEEP1288 retained fact"}).status == "success"
        found = MemorySearchTool(manager).execute({"query": "TOPAZKEEP1288", "min_score": 0})
        assert found.status == "success"
        assert "retained fact" in found.result
        assert manager.storage.get_file_hash("memory/blank.md") is None
        assert manager.storage.list_paths("memory") == ["memory/keep.md"]
    finally:
        manager.storage.close()
