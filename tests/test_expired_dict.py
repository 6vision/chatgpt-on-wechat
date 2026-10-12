from datetime import datetime, timedelta

import pytest

from common import expired_dict
from common.expired_dict import ExpiredDict


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


def test_a_write_drops_entries_that_nobody_reads_again(clock):
    # The channel dedup caches write each message id once and never look it up
    # again, so expired ids have to go without anyone asking for them.
    seen = ExpiredDict(10)
    for i in range(100):
        seen[f"msg-{i}"] = True

    clock.advance(11)
    seen["msg-new"] = True

    assert dict.__len__(seen) == 1
    assert list(seen) == ["msg-new"]


def test_listing_the_keys_does_not_keep_entries_alive(clock):
    cache = ExpiredDict(10)
    cache["a"] = 1

    clock.advance(6)
    cache.keys()
    cache.items()
    cache.values()
    list(cache)
    clock.advance(5)

    assert "a" not in cache


def test_reading_a_key_still_extends_its_lifetime(clock):
    sessions = ExpiredDict(10)
    sessions["user-1"] = "session"

    clock.advance(6)
    assert sessions["user-1"] == "session"
    clock.advance(5)

    assert sessions.get("user-1") == "session"


def test_views_and_len_leave_out_expired_entries(clock):
    cache = ExpiredDict(10)
    cache["old"] = 1
    clock.advance(6)
    cache["new"] = 2
    clock.advance(5)

    assert len(cache) == 1
    assert cache.keys() == ["new"]
    assert cache.values() == [2]
    assert cache.items() == [("new", 2)]


def test_pop_returns_the_stored_value(clock):
    cache = ExpiredDict(10)
    cache["a"] = ("session-1", "agent-1")

    assert cache.pop("a") == ("session-1", "agent-1")
    assert cache.pop("a", None) is None
    with pytest.raises(KeyError):
        cache.pop("a")


def test_pop_treats_an_expired_entry_as_missing(clock):
    cache = ExpiredDict(10)
    cache["a"] = 1
    clock.advance(11)

    assert cache.pop("a", "gone") == "gone"
    assert dict.__len__(cache) == 0
    with pytest.raises(KeyError):
        cache.pop("a")
