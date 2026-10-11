from datetime import datetime
from agent.evolution import backup

class FrozenDateTime:
    @staticmethod
    def now():
        return datetime(2026, 1, 1, 12, 0, 0)

def test_same_timestamp_snapshots_remain_independently_restorable(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "datetime", FrozenDateTime)
    monkeypatch.setattr(backup.time, "time", lambda: 1767268800.123)
    monkeypatch.setattr(backup.time, "time_ns", lambda: 1767268800123000000)
    target = tmp_path / "MEMORY.md"
    target.write_text("first version")
    first = backup.create_backup(tmp_path, [target])
    target.write_text("second version")
    second = backup.create_backup(tmp_path, [target])
    assert first != second
    assert backup.restore_backup(tmp_path, first)
    assert target.read_text() == "first version"
    assert backup.restore_backup(tmp_path, second)
    assert target.read_text() == "second version"

def test_forced_id_collision_cannot_remove_original_snapshot(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(backup, "datetime", FrozenDateTime)
    monkeypatch.setattr(backup.time, "time", lambda: 1767268800.123)
    monkeypatch.setattr(backup.time, "time_ns", lambda: 1767268800123000000)
    import uuid
    monkeypatch.setattr(uuid, "uuid4", lambda: SimpleNamespace(int=1))
    target = tmp_path / "MEMORY.md"
    target.write_text("first version")
    first = backup.create_backup(tmp_path, [target])
    target.write_text("second version")
    assert backup.create_backup(tmp_path, [target]) is None
    assert backup.restore_backup(tmp_path, first)
    assert target.read_text() == "first version"
