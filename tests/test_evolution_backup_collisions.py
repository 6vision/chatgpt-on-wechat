from datetime import datetime
from agent.evolution import backup

class FrozenDateTime:
    @staticmethod
    def now():
        return datetime(2026, 1, 1, 12, 0, 0)

def freeze(monkeypatch):
    monkeypatch.setattr(backup, "datetime", FrozenDateTime)
    monkeypatch.setattr(backup.time, "time", lambda: 1767268800.123)

def test_same_timestamp_snapshots_remain_independently_restorable(tmp_path, monkeypatch):
    freeze(monkeypatch)
    target = tmp_path / "MEMORY.md"
    target.write_text("first version")
    first = backup.create_backup(tmp_path, [target])
    target.write_text("second version")
    second = backup.create_backup(tmp_path, [target])
    assert first != second
    assert sorted([first, second]) == [first, second]
    assert backup.restore_backup(tmp_path, first)
    assert target.read_text() == "first version"
    assert backup.restore_backup(tmp_path, second)
    assert target.read_text() == "second version"

def test_failed_snapshot_does_not_remove_an_existing_one(tmp_path, monkeypatch):
    freeze(monkeypatch)
    target = tmp_path / "MEMORY.md"
    target.write_text("first version")
    first = backup.create_backup(tmp_path, [target])
    monkeypatch.setattr(backup.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert backup.create_backup(tmp_path, [target]) is None
    monkeypatch.undo()
    assert backup.restore_backup(tmp_path, first)
    assert target.read_text() == "first version"
