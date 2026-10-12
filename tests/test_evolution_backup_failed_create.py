"""A failed create_backup must not cost the user a restorable undo slot."""

import shutil

from agent.evolution import backup as backup_module
from agent.evolution.backup import (
    _MANIFEST_NAME,
    _MAX_BACKUPS,
    _prune_old_backups,
    create_backup,
    restore_backup,
)


def _workspace(tmp_path, count=1):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(count):
        path = tmp_path / f"f{i}.md"
        path.write_text(f"original {i}", encoding="utf-8")
        files.append(path)
    return files


def _root(tmp_path):
    return tmp_path / "memory" / ".evolution_backups"


def _make_backups(tmp_path, files, count):
    """Create ``count`` snapshots and force distinct, increasing ids.

    ``create_backup`` derives its id from the wall clock, so back-to-back calls
    can collide on one directory. Renaming afterwards keeps the ordering this
    test needs without depending on how fast the loop runs.
    """
    root = _root(tmp_path)
    serial = 1000
    for _ in range(count):
        create_backup(tmp_path, files)
        for index, directory in enumerate(sorted(p for p in root.iterdir() if p.is_dir())):
            serial += 1
            directory.rename(root / f"20260101-{serial:06d}")
    return sorted(p for p in root.iterdir() if p.is_dir())


def _fail_copies_after(monkeypatch, module, succeed=1):
    """Make ``shutil.copy2`` raise on every call past the ``succeed``-th."""
    real_copy2 = shutil.copy2
    calls = {"n": 0}

    def flaky(src, dst, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] > succeed:
            raise OSError("no space left on device")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(module.shutil, "copy2", flaky)
    return calls


# --- the failure path -------------------------------------------------------


def test_a_failed_snapshot_leaves_no_directory_behind(tmp_path, monkeypatch):
    files = _workspace(tmp_path, 3)
    _fail_copies_after(monkeypatch, backup_module, succeed=1)

    assert create_backup(tmp_path, files) is None
    assert not _root(tmp_path).exists() or list(_root(tmp_path).iterdir()) == []


def test_a_failed_snapshot_leaves_nothing_to_restore(tmp_path, monkeypatch):
    files = _workspace(tmp_path, 2)
    _fail_copies_after(monkeypatch, backup_module, succeed=0)

    assert create_backup(tmp_path, files) is None
    # No id was returned, and the debris cannot be reached by guessing one.
    leftovers = [p.name for p in _root(tmp_path).iterdir() if p.is_dir()]
    assert leftovers == []


def test_a_manifest_write_failure_also_cleans_up(tmp_path, monkeypatch):
    # The manifest is written last, so failing it is the narrowest window: the
    # payload is complete but the snapshot is still unusable.
    files = _workspace(tmp_path, 2)
    real_write_text = backup_module.Path.write_text

    def flaky_write_text(self, *args, **kwargs):
        if self.name == _MANIFEST_NAME:
            raise OSError("no space left on device")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(backup_module.Path, "write_text", flaky_write_text)

    assert create_backup(tmp_path, files) is None
    assert not _root(tmp_path).exists() or list(_root(tmp_path).iterdir()) == []


def test_a_restorable_snapshot_is_unaffected_by_the_cleanup(tmp_path):
    files = _workspace(tmp_path, 2)
    backup_id = create_backup(tmp_path, files)

    assert backup_id is not None
    files[0].write_text("changed", encoding="utf-8")
    assert restore_backup(tmp_path, backup_id) is True
    assert files[0].read_text(encoding="utf-8") == "original 0"


# --- the pruner -------------------------------------------------------------


def test_debris_does_not_evict_a_restorable_snapshot(tmp_path, monkeypatch):
    # Ten good snapshots, then debris that sorts newest -- the shape that cost
    # the user an undo point on unfixed code.
    files = _workspace(tmp_path)
    _make_backups(tmp_path, files, _MAX_BACKUPS)
    root = _root(tmp_path)
    debris = root / "20260999-000000-999"
    debris.mkdir()
    (debris / "0.bak").write_text("partial", encoding="utf-8")

    _prune_old_backups(root)

    remaining = sorted(p for p in root.iterdir() if p.is_dir())
    assert debris not in remaining
    assert all((p / _MANIFEST_NAME).is_file() for p in remaining)
    assert len(remaining) == _MAX_BACKUPS
    # Every retained snapshot is still undoable.
    for directory in remaining:
        assert (directory / "0.bak").is_file()


def test_the_pruner_still_evicts_the_oldest_real_snapshots(tmp_path):
    files = _workspace(tmp_path)
    _make_backups(tmp_path, files, _MAX_BACKUPS + 3)
    root = _root(tmp_path)

    _prune_old_backups(root)

    remaining = sorted(p.name for p in root.iterdir() if p.is_dir())
    assert len(remaining) == _MAX_BACKUPS
    assert remaining == sorted(remaining)
    assert remaining[-1] == sorted(p.name for p in root.iterdir() if p.is_dir())[-1]


def test_a_truncated_manifest_still_holds_a_slot(tmp_path):
    # A zero-byte manifest is a file, so this directory counts as complete even
    # though restore_backup cannot parse it. The pruner checks presence, not
    # validity -- pinning that boundary so validating the JSON one day is a
    # deliberate decision rather than an accident.
    files = _workspace(tmp_path)
    made = _make_backups(tmp_path, files, _MAX_BACKUPS)
    root = _root(tmp_path)
    broken = root / "20260999-000000-999"
    broken.mkdir()
    (broken / _MANIFEST_NAME).write_text("", encoding="utf-8")
    (broken / "0.bak").write_text("payload", encoding="utf-8")

    _prune_old_backups(root)

    remaining = sorted(p for p in root.iterdir() if p.is_dir())
    # It sorts newest, so it keeps its slot and the oldest real snapshot goes.
    assert broken in remaining
    assert len(remaining) == _MAX_BACKUPS
    assert made[0] not in remaining
    assert made[-1] in remaining


def test_the_slot_count_matches_what_the_user_can_undo(tmp_path, monkeypatch):
    files = _workspace(tmp_path)
    _make_backups(tmp_path, files, _MAX_BACKUPS)

    real_copy2 = shutil.copy2

    def boom(src, dst, *args, **kwargs):
        raise OSError("no space left on device")

    for _ in range(3):
        monkeypatch.setattr(backup_module.shutil, "copy2", boom)
        assert create_backup(tmp_path, files) is None
    monkeypatch.setattr(backup_module.shutil, "copy2", real_copy2)

    remaining = sorted(p for p in _root(tmp_path).iterdir() if p.is_dir())
    restorable = [p for p in remaining if (p / _MANIFEST_NAME).is_file()]
    assert len(remaining) == len(restorable) == _MAX_BACKUPS
