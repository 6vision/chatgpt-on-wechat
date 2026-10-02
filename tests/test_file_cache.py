"""channel/file_cache.py: a session's files form one batch, attached to the
user's next text message, and expire TTL seconds after the most recent file."""
from datetime import datetime, timedelta

import pytest

from channel.file_cache import FileCache
from common import expired_dict


class FakeClock:
    def __init__(self):
        self.current = datetime(2026, 1, 1)

    def now(self):
        return self.current

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(expired_dict, "datetime", fake)
    return fake


def paths(files):
    return [f["path"] for f in files]


def test_ttl_runs_from_the_most_recent_file(clock):
    cache = FileCache(ttl=300)
    cache.add("s1", "/tmp/a.png", "image")
    clock.advance(240)
    cache.add("s1", "/tmp/b.png", "image")
    clock.advance(240)

    assert paths(cache.get("s1")) == ["/tmp/a.png", "/tmp/b.png"]


def test_batch_expires_when_nothing_new_arrives(clock):
    cache = FileCache(ttl=300)
    cache.add("s1", "/tmp/a.png", "image")
    clock.advance(301)

    assert cache.get("s1") == []


def test_upload_at_the_ttl_boundary_keeps_the_batch(clock):
    cache = FileCache(ttl=300)
    cache.add("s1", "/tmp/a.png", "image")
    clock.advance(300)
    cache.add("s1", "/tmp/b.png", "image")

    assert paths(cache.get("s1")) == ["/tmp/a.png", "/tmp/b.png"]


def test_new_file_after_expiry_starts_a_fresh_batch(clock):
    cache = FileCache(ttl=300)
    cache.add("s1", "/tmp/old.pdf", "file")
    cache.add("s1", "/tmp/a.png", "image")
    clock.advance(301)
    cache.add("s1", "/tmp/a.png", "image")

    assert cache.get("s1") == [{"path": "/tmp/a.png", "type": "image"}]


def test_re_adding_the_same_file_is_deduped_and_refreshes_the_window(clock):
    cache = FileCache(ttl=300)
    cache.add("s1", "/tmp/a.png", "image")
    clock.advance(240)
    cache.add("s1", "/tmp/a.png", "image")
    clock.advance(240)

    assert paths(cache.get("s1")) == ["/tmp/a.png"]


def test_a_later_write_reclaims_batches_nobody_asked_about(clock):
    cache = FileCache(ttl=300)
    for session_id in ("s1", "s2", "s3"):
        cache.add(session_id, f"/tmp/{session_id}.png", "image")
        clock.advance(301)
    cache.add("s4", "/tmp/s4.png", "image")

    assert sorted(dict.keys(cache.cache)) == ["s4"]


def test_a_live_batch_survives_another_session_write(clock):
    cache = FileCache(ttl=300)
    cache.add("s1", "/tmp/a.png", "image")
    clock.advance(100)
    cache.add("s2", "/tmp/b.png", "image")

    assert paths(cache.get("s1")) == ["/tmp/a.png"]
    assert paths(cache.get("s2")) == ["/tmp/b.png"]


def test_clear_drops_the_batch(clock):
    cache = FileCache(ttl=300)
    cache.add("s1", "/tmp/a.png", "image")
    cache.clear("s1")
    cache.clear("s1")

    assert cache.get("s1") == []
