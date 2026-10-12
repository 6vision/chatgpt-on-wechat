from types import SimpleNamespace
from agent.tools.memory.memory_get import MemoryGetTool
from agent.tools.read.read import Read


def test_memory_get_uses_the_shared_credential_guard_when_workspace_is_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    credential = tmp_path / ".cow" / ".env"
    credential.parent.mkdir()
    credential.write_text("SYNTHETIC_PRIVATE_VALUE", encoding="utf-8")
    manager = SimpleNamespace(config=SimpleNamespace(get_workspace=lambda: tmp_path))
    assert Read({"cwd": str(tmp_path)}).execute({"path": str(credential)}).status == "error"
    result = MemoryGetTool(manager).execute({"path": str(credential)})
    assert result.status == "error"
    assert "SYNTHETIC_PRIVATE_VALUE" not in str(result.result)


def test_real_memory_content_remains_readable(tmp_path):
    page = tmp_path / "memory" / "note.md"
    page.parent.mkdir()
    page.write_text("safe memory", encoding="utf-8")
    manager = SimpleNamespace(config=SimpleNamespace(get_workspace=lambda: tmp_path))
    result = MemoryGetTool(manager).execute({"path": "note.md"})
    assert result.status == "success"
    assert "safe memory" in result.result
