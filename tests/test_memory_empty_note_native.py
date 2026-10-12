"""Clearing a memory note through Write drops its indexed content without embedding blank text."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from agent.memory.embedding.provider import OpenAIEmbeddingProvider
from agent.tools.write.write import Write
from agent.tools.memory.memory_search import MemorySearchTool


@pytest.fixture
def make(tmp_path):
    managers = []

    def factory(provider=None):
        (tmp_path / "knowledge").mkdir()
        managers.append(MemoryManager(MemoryConfig(workspace_root=str(tmp_path)), embedding_provider=provider))
        writer = Write(config={"cwd": str(tmp_path), "memory_manager": managers[-1]})
        return managers[-1], lambda path, text: writer.execute({"path": path, "content": text}).status
    yield factory
    for manager in managers:
        manager.storage.close()


@pytest.fixture
def embedding():
    calls, state = [], {"status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"data": [{"index": i, "embedding": [1.0, 0.0]}
                                        for i in range(len(calls[-1]["input"]))]}).encode()
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield OpenAIEmbeddingProvider(model="fixture-model", api_key="fixture-key", dimensions=2,
                                  api_base=f"http://127.0.0.1:{server.server_port}/v1"), calls, state
    server.shutdown()
    server.server_close()


def _search(manager, query):
    result = MemorySearchTool(manager).execute({"query": query, "min_score": 0})
    assert result.status == "success"
    return str(result.result)


@pytest.mark.parametrize("replacement", ["", " \t\n\n"])
def test_clearing_a_note_removes_its_searchable_content(make, replacement):
    manager, write = make()
    for path, text in [("memory/blank.md", " \t\n"), ("memory/owned.md", "# Note\nQUARTZCLEAR8812 old fact\n"),
                       ("memory/keep.md", "# Keep\nTOPAZKEEP9913 retained fact\n")]:
        assert write(path, text) == "success"
    assert "QUARTZCLEAR8812" in _search(manager, "QUARTZCLEAR8812")
    assert write("memory/owned.md", replacement) == "success"
    assert "old fact" not in _search(manager, "QUARTZCLEAR8812")
    assert manager.storage.get_file_hash("memory/owned.md") == manager.storage.compute_hash(replacement)
    assert "TOPAZKEEP9913" in _search(manager, "TOPAZKEEP9913")
    assert write("memory/owned.md", "# New\nAMBERNEW5514 new fact\n") == "success"
    assert "AMBERNEW5514" in _search(manager, "AMBERNEW5514")
    assert "old fact" not in _search(manager, "QUARTZCLEAR8812")
    assert manager.storage.get_file_hash("memory/blank.md") is None
    assert "memory/blank.md" not in manager.storage.list_paths("memory")


def test_failed_embedding_keeps_pending_updates_and_blank_text_is_never_embedded(make, embedding):
    provider, calls, state = embedding
    manager, write = make(provider)
    storage = manager.storage
    write("memory/clear.md", "QUARTZOLD3341 old fact")
    write("memory/change.md", "TOPAZOLD2291 kept until success")
    asyncio.run(manager.sync())
    old_hash = storage.get_file_hash("memory/clear.md")
    write("memory/clear.md", "")
    write("memory/change.md", "TOPAZNEW2291 replacement")
    state["status"] = 500
    asyncio.run(manager.sync())
    assert manager._dirty is True and storage.get_file_hash("memory/clear.md") == old_hash
    assert storage.search_keyword("QUARTZOLD3341") and storage.search_keyword("TOPAZOLD2291")
    assert storage.search_keyword("TOPAZNEW2291") == []
    state["status"] = 200
    asyncio.run(manager.sync())
    assert manager._dirty is False
    assert storage.search_keyword("QUARTZOLD3341") == [] and storage.search_keyword("TOPAZNEW2291")
    count = len(calls)
    assert write("memory/change.md", "") == "success"
    asyncio.run(manager.sync())
    assert len(calls) == count
    assert storage.get_file_hash("memory/change.md") == storage.compute_hash("")
    assert storage.conn.execute("SELECT COUNT(*) FROM chunks WHERE path = ?", ("memory/change.md",)).fetchone()[0] == 0
    assert all(text.strip() for call in calls for text in call["input"])
