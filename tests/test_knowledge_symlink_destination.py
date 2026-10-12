import pytest
from agent.knowledge.service import KnowledgeService

def service(tmp_path, monkeypatch):
    (tmp_path / "knowledge" / "notes").mkdir(parents=True)
    svc = KnowledgeService(str(tmp_path))
    monkeypatch.setattr(svc, "_sync_index", lambda *a, **k: None)
    return svc

def test_import_cannot_overwrite_external_symlink_target(tmp_path, monkeypatch):
    svc = service(tmp_path, monkeypatch)
    external = tmp_path / "private.md"
    external.write_text("private original")
    (tmp_path / "knowledge/notes/doc.md").symlink_to(external)
    result = svc.import_documents("notes", [{"filename": "doc.md", "content": "replacement"}], "overwrite")
    assert result["failed"] == 1 and result["imported"] == 0
    assert external.read_text() == "private original"

def test_create_rejects_dangling_external_symlink(tmp_path, monkeypatch):
    svc = service(tmp_path, monkeypatch)
    external = tmp_path / "not-created.md"
    (tmp_path / "knowledge/notes/doc.md").symlink_to(external)
    with pytest.raises(ValueError, match="outside knowledge"):
        svc.create_document("notes/doc.md", "replacement")
    assert not external.exists()

def test_regular_import_and_internal_symlink_remain_supported(tmp_path, monkeypatch):
    svc = service(tmp_path, monkeypatch)
    real = tmp_path / "knowledge/notes/real.md"
    real.write_text("old")
    (tmp_path / "knowledge/notes/doc.md").symlink_to(real)
    result = svc.import_documents("notes", [{"filename": "doc.md", "content": "new"}], "overwrite")
    assert result["imported"] == 1
    assert real.read_text() == "new"
