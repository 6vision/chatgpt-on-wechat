"""Concurrent first adds to one session must keep every file."""

import threading

from channel.file_cache import FileCache


def test_concurrent_first_adds_keep_both_files(monkeypatch):
    cache = FileCache()
    original_get = cache.cache.get
    first_read, release = threading.Event(), threading.Event()
    reads = []

    def slow_first_get(key):
        value = original_get(key)
        reads.append(key)
        if len(reads) == 1:
            first_read.set()
            release.wait(0.3)
        return value

    monkeypatch.setattr(cache.cache, "get", slow_first_get)
    first = threading.Thread(target=cache.add, args=("s", "a.png"))
    second = threading.Thread(target=cache.add, args=("s", "b.png"))
    first.start()
    assert first_read.wait(2)
    second.start()
    release.set()
    first.join(2)
    second.join(2)

    assert {f["path"] for f in cache.get("s")} == {"a.png", "b.png"}


def test_duplicate_file_is_kept_once_and_clear_is_per_session():
    cache = FileCache()
    cache.add("first", "x.png")
    cache.add("first", "x.png")
    cache.add("second", "y.pdf", "file")
    assert cache.get("first") == [{"path": "x.png", "type": "image"}]
    cache.clear("first")
    assert cache.get("first") == []
    assert cache.get("second") == [{"path": "y.pdf", "type": "file"}]
