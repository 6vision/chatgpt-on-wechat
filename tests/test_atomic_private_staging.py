import os
import stat
import pytest
from common import atomic_write


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
@pytest.mark.parametrize("exists", [False, True])
def test_live_staging_is_private_before_content_is_serialized(tmp_path, exists):
    target = tmp_path / "credentials.json"
    if exists:
        target.write_text("old", encoding="utf-8")
        target.chmod(0o600)

    def write(handle):
        handle.write("synthetic-private-content")
        handle.flush()
        staged = list(tmp_path.glob(".*.tmp"))
        assert len(staged) == 1
        assert stat.S_IMODE(staged[0].stat().st_mode) & 0o077 == 0

    previous = os.umask(0o022)
    try:
        atomic_write._replace(target, write)
    finally:
        os.umask(previous)
    assert target.read_text() == "synthetic-private-content"
    assert not list(tmp_path.glob(".*.tmp"))
