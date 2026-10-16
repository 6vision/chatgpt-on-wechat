"""A failed document publication must retain the previously saved knowledge."""
import builtins
import errno
import io
from pathlib import Path

import pytest
import web

from agent.knowledge.service import KnowledgeService
from channel.web.api import knowledge as knowledge_api


@pytest.fixture
def knowledge(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "notes").mkdir()
    document = root / "notes" / "a.md"
    document.write_text("# Saved knowledge\nPreviously verified contents.\n", encoding="utf-8")
    index = root / "index.md"
    index.write_text("# Knowledge\n- [Saved](./notes/a.md) — Retained user summary\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(KnowledgeService, "_reindex", lambda self, *a, **k: calls.append((a, k)))
    return KnowledgeService(str(tmp_path)), document, index, calls


def fail_partial_writes(monkeypatch, target):
    """Write actual prefix bytes, then fail either the destination or its stage."""
    original_builtin, original_io = builtins.open, io.open
    events = []

    class Writer:
        def __init__(self, handle, path):
            self.handle, self.path = handle, path

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def write(self, text):
            self.handle.write(text[:7])
            self.handle.flush()
            events.append(self.path)
            raise OSError(errno.ENOSPC, "owned partial-write fixture")

    def wrap(original):
        def opened(file, mode="r", *args, **kwargs):
            handle = original(file, mode, *args, **kwargs)
            if isinstance(file, (str, Path)) and "w" in mode:
                path = Path(file)
                if path.parent == target.parent and (
                    path.name == target.name or path.name.startswith(f".{target.name}.")
                ):
                    return Writer(handle, str(path))
            return handle
        return opened

    monkeypatch.setattr(builtins, "open", wrap(original_builtin))
    monkeypatch.setattr(io, "open", wrap(original_io))
    return events


def test_failed_overwrite_retains_document_and_index(knowledge, monkeypatch):
    service, document, index, indexed = knowledge
    saved_document, saved_index = document.read_bytes(), index.read_bytes()
    events = fail_partial_writes(monkeypatch, document)
    result = service.dispatch("create_document", {"path": "notes/a.md", "content": "# Replacement\nNew text.", "overwrite": True})
    assert result["code"] == 500
    assert events
    assert document.read_bytes() == saved_document
    assert index.read_bytes() == saved_index
    assert not indexed
    assert sorted(p.name for p in document.parent.iterdir()) == ["a.md"]


def test_failed_import_retains_document_and_index(knowledge, monkeypatch):
    service, document, index, indexed = knowledge
    saved_document, saved_index = document.read_bytes(), index.read_bytes()
    events = fail_partial_writes(monkeypatch, document)
    result = service.import_documents("notes", [{"filename": "a.md", "content": "# Imported replacement\n"}], "overwrite")
    assert result["imported"] == 0 and result["failed"] == 1
    assert events
    assert document.read_bytes() == saved_document
    assert index.read_bytes() == saved_index
    assert not indexed
    assert sorted(p.name for p in document.parent.iterdir()) == ["a.md"]


def test_failed_index_rebuild_retains_user_summaries(knowledge, monkeypatch):
    service, _, index, _ = knowledge
    previous = index.read_bytes()
    events = fail_partial_writes(monkeypatch, index)
    assert service.rebuild_index_md() is False
    assert events
    assert index.read_bytes() == previous
    assert not list(index.parent.glob(".index.md.*.tmp"))


@pytest.mark.parametrize("operation", ["overwrite", "import"])
def test_successful_publication_replaces_all_bytes_and_preserves_summary(knowledge, operation):
    service, document, index, indexed = knowledge
    text = "# Published replacement\nComplete new contents.\n"
    if operation == "overwrite":
        assert service.dispatch("create_document", {"path": "notes/a.md", "content": text, "overwrite": True})["code"] == 200
    else:
        result = service.import_documents("notes", [{"filename": "a.md", "content": text}], "overwrite")
        assert result["imported"] == 1 and result["failed"] == 0
    assert document.read_text() == text
    assert "Retained user summary" in index.read_text()
    assert len(indexed) == 1
    assert not list(document.parent.glob(".a.md.*.tmp"))


def test_skip_import_and_protected_overwrite_preserve_existing_bytes(knowledge):
    service, document, index, indexed = knowledge
    previous = document.read_bytes(), index.read_bytes()
    skipped = service.import_documents("notes", [{"filename": "a.md", "content": "ignored"}], "skip")
    assert skipped["skipped"] == 1 and skipped["imported"] == 0
    assert service.dispatch("create_document", {"path": "index.md", "content": "not allowed", "overwrite": True})["code"] == 403
    assert (document.read_bytes(), index.read_bytes()) == previous
    assert not indexed


@pytest.mark.parametrize("operation", ["create_document", "import_documents"])
def test_console_action_failure_keeps_saved_document(knowledge, monkeypatch, operation):
    import json

    service, document, index, indexed = knowledge
    previous = document.read_bytes(), index.read_bytes()
    monkeypatch.setattr(knowledge_api, "_require_auth", lambda: None)
    monkeypatch.setattr(knowledge_api, "_get_workspace_root", lambda **kwargs: service.workspace_root)
    app = web.application(("/action", "KnowledgeActionHandler"), vars(knowledge_api))
    events = fail_partial_writes(monkeypatch, document)
    payload = {"path": "notes/a.md", "content": "# Console replacement\n", "overwrite": True}
    if operation == "import_documents":
        payload = {"target_category": "notes", "files": [{"filename": "a.md", "content": "# Console import\n"}], "conflict_strategy": "overwrite"}
    response = json.loads(app.request("/action", method="POST", data=json.dumps({"action": operation, "payload": payload})).data)
    if operation == "create_document":
        assert response["status"] == "error" and response["code"] == 500
    else:
        assert response["payload"]["failed"] == 1 and response["payload"]["imported"] == 0
    assert events
    assert (document.read_bytes(), index.read_bytes()) == previous
    assert not indexed
