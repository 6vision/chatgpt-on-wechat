"""An in-memory cursor update remains pending until its durable write succeeds."""
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from channel.wechat_kf import wechat_kf_cursor_store as module


def failing_once_replace(monkeypatch):
    original = module.os.replace
    calls = []

    def replace(source, destination):
        calls.append((source, destination))
        if len(calls) == 1:
            raise OSError(28, "No space left on device")
        original(source, destination)

    monkeypatch.setattr(module.os, "replace", replace)
    return calls


def test_same_cursor_is_retried_after_a_failed_flush(monkeypatch, tmp_path):
    path = tmp_path / "cursor.json"
    path.write_text('{"kf": "before"}')
    store = module.CursorStore(str(path))
    calls = failing_once_replace(monkeypatch)
    store.set("kf", "after")
    assert json.loads(path.read_text()) == {"kf": "before"}
    store.set("kf", "after")
    assert json.loads(path.read_text()) == {"kf": "after"}
    assert len(calls) == 2
    assert not path.with_suffix(".json.tmp").exists()


def test_next_callback_read_retries_pending_cursor(monkeypatch, tmp_path):
    path = tmp_path / "cursor.json"
    path.write_text('{"kf": "before"}')
    store = module.CursorStore(str(path))
    calls = failing_once_replace(monkeypatch)
    store.set("kf", "after")
    assert json.loads(path.read_text())["kf"] == "before"
    assert store.get("kf") == "after"
    assert json.loads(path.read_text())["kf"] == "after"
    assert len(calls) == 2


def test_clean_unchanged_cursor_does_not_rewrite(monkeypatch, tmp_path):
    path = tmp_path / "cursor.json"
    store = module.CursorStore(str(path))
    replace = Mock(wraps=module.os.replace)
    monkeypatch.setattr(module.os, "replace", replace)
    store.set("kf", "after")
    assert store.get("kf") == "after"
    store.set("kf", "after")
    replace.assert_called_once()
    assert module.CursorStore(str(path)).get("kf") == "after"


def test_concurrent_kf_updates_keep_all_persisted_values(tmp_path):
    path = tmp_path / "cursor.json"
    store = module.CursorStore(str(path))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: store.set(f"kf-{n}", f"cursor-{n}"), range(8)))
    assert json.loads(path.read_text()) == {f"kf-{n}": f"cursor-{n}" for n in range(8)}
