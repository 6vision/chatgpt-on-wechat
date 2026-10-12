from pathlib import Path
from agent.tools.write.write import Write

def test_saved_memory_file_reports_success_when_notification_fails(tmp_path):
    class Config:
        def get_workspace(self):
            return Path(tmp_path)
    class Memory:
        config = Config()
        def mark_dirty(self):
            raise RuntimeError("index unavailable")
    result = Write({"cwd": str(tmp_path), "memory_manager": Memory()}).execute({"path": "MEMORY.md", "content": "saved fact"})
    assert (tmp_path / "MEMORY.md").read_text() == "saved fact"
    assert result.status == "success", result.result
    assert "notification failed" in result.result["warning"]

def test_nonmemory_write_does_not_notify(tmp_path):
    class Memory:
        def mark_dirty(self):
            raise AssertionError("unexpected notification")
    result = Write({"cwd": str(tmp_path), "memory_manager": Memory()}).execute({"path": "notes.txt", "content": "saved"})
    assert result.status == "success"
