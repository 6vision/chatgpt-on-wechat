import os
import stat

import pytest

from common import atomic_write

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")


def _staged_mode(tmp_path, target):
    modes = []

    def write(handle):
        handle.write("content")
        handle.flush()
        modes.extend(stat.S_IMODE(p.stat().st_mode) for p in tmp_path.glob(".*.tmp"))

    previous = os.umask(0o022)
    try:
        atomic_write._replace(target, write)
    finally:
        os.umask(previous)
    assert target.read_text() == "content"
    assert not list(tmp_path.glob(".*.tmp"))
    return modes


def test_a_private_target_is_staged_privately(tmp_path):
    target = tmp_path / "credentials.json"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o600)
    assert _staged_mode(tmp_path, target) == [0o600]
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_new_file_keeps_the_umask_default(tmp_path):
    target = tmp_path / "notes.md"
    assert _staged_mode(tmp_path, target) == [0o644]
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
