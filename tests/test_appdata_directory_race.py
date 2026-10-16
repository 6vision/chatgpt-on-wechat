from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import config


def test_concurrent_appdata_initialization_succeeds(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    barrier = Barrier(2)
    exists = os.path.exists

    def synchronized_exists(path):
        result = exists(path)
        if os.fspath(path) == str(target) and not result:
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(config, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(config, "conf", lambda: {"appdata_dir": "appdata"})
    monkeypatch.setattr(config.os.path, "exists", synchronized_exists)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = [workers.submit(config.get_appdata_dir) for _ in range(2)]
        assert [future.result(timeout=5) for future in pending] == [str(target), str(target)]
    assert target.is_dir()


def test_existing_appdata_directory_preserved(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    marker = target / "saved.txt"
    marker.write_text("saved")
    monkeypatch.setattr(config, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(config, "conf", lambda: {"appdata_dir": "appdata"})
    assert config.get_appdata_dir() == str(target)
    assert marker.read_text() == "saved"
