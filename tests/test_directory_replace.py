"""Native rollback, ownership and staging controls for directory replacement."""

import os
import errno
from pathlib import Path

import pytest

from common.directory_replace import replace_directory


def _directory(path, contents):
    path.mkdir()
    (path / "notes.txt").write_text(contents, encoding="utf-8")
    return path


@pytest.mark.parametrize("move", [False, True])
def test_complete_replacement_retains_only_the_new_target(tmp_path, move):
    source = _directory(tmp_path / "source", "new notes")
    target = _directory(tmp_path / "target", "old notes")
    replace_directory(str(source), str(target), move_source=move)
    assert (target / "notes.txt").read_text() == "new notes"
    assert source.exists() is not move
    assert list(tmp_path.glob(".target.replace-*")) == []


def test_failed_restoration_keeps_the_previous_directory_for_recovery(tmp_path, monkeypatch):
    source = _directory(tmp_path / "source", "new notes")
    target = _directory(tmp_path / "target", "old notes")
    rename = os.rename

    def refuse_target(src, dst):
        if Path(dst) == target:
            raise PermissionError("target temporarily unavailable")
        return rename(src, dst)

    monkeypatch.setattr(os, "rename", refuse_target)
    with pytest.raises(PermissionError, match="temporarily unavailable"):
        replace_directory(str(source), str(target))
    preserved = list(tmp_path.glob(".target.replace-*/previous/notes.txt"))
    assert len(preserved) == 1
    assert preserved[0].read_text() == "old notes"
    assert (source / "notes.txt").read_text() == "new notes"


def test_failed_restoration_preserves_the_original_promotion_exception(tmp_path, monkeypatch):
    source = _directory(tmp_path / "source", "new notes")
    target = _directory(tmp_path / "target", "old notes")
    rename = os.rename
    promotion_error = PermissionError("promotion denied")
    rollback_error = OSError(errno.ENOSPC, "restoration denied")

    def fail_publication_and_restoration(src, dst):
        if Path(dst) == target:
            raise rollback_error if Path(src).name == "previous" else promotion_error
        return rename(src, dst)

    monkeypatch.setattr(os, "rename", fail_publication_and_restoration)
    with pytest.raises(PermissionError) as failed:
        replace_directory(str(source), str(target))
    assert failed.value is promotion_error
    preserved = list(tmp_path.glob(".target.replace-*/previous/notes.txt"))
    assert len(preserved) == 1
    assert preserved[0].read_text() == "old notes"
    assert (source / "notes.txt").read_text() == "new notes"


def test_target_alias_cannot_replace_a_directory_elsewhere(tmp_path):
    source = _directory(tmp_path / "source", "new notes")
    outside = _directory(tmp_path / "elsewhere", "unrelated notes")
    alias = tmp_path / "target"
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(OSError, match="symlink"):
        replace_directory(str(source), str(alias))
    assert alias.is_symlink()
    assert (outside / "notes.txt").read_text() == "unrelated notes"


@pytest.mark.parametrize("direction", ["same", "source_inside", "target_inside"])
def test_overlapping_paths_leave_all_input_files_unchanged(tmp_path, direction):
    root = _directory(tmp_path / "root", "original notes")
    child = _directory(root / "child", "child notes")
    source, target = {
        "same": (root, root), "source_inside": (child, root), "target_inside": (root, child),
    }[direction]
    original = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="overlap"):
        replace_directory(str(source), str(target))
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == original
