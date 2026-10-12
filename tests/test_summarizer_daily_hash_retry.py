"""The day-level dedup hash must be earned, not spent on dispatch."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory.summarizer import MemoryFlushManager


SUMMARY = "- the user chose copy-on-write for the cache layer\n"


def _text(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


class _StubModel:
    def __init__(self, content: str = SUMMARY):
        self.content = content
        self.calls = 0

    def call(self, request):
        self.calls += 1
        return {"choices": [{"message": {"content": self.content}}]}


class _UnreachableModel:
    """Every call fails the way a provider outage does."""

    def __init__(self):
        self.calls = 0

    def call(self, request):
        self.calls += 1
        raise ConnectionError("provider is unreachable")


class _FlakyModel:
    """Refuses the first call, then behaves -- an outage that clears."""

    def __init__(self, content: str = SUMMARY):
        self.content = content
        self.calls = 0

    def call(self, request):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("provider is unreachable")
        return {"choices": [{"message": {"content": self.content}}]}


class _NoSummaryManager(MemoryFlushManager):
    """A manager whose summariser produces nothing at all.

    The rule-based fallback rescues an unreachable provider, so an outage by
    itself still lands a daily file -- this is the case where nothing does:
    _summarize_messages returns None and the flush has to be retried.
    """

    def _summarize_messages(self, messages, max_messages=0):
        return None


class _FlakyNoSummaryManager(_NoSummaryManager):
    """Produces nothing until ``recover()`` is called, then behaves normally."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recovered = False

    def recover(self):
        self.recovered = True

    def _summarize_messages(self, messages, max_messages=0):
        if not self.recovered:
            return None
        return MemoryFlushManager._summarize_messages(self, messages, max_messages)


_TODAY = [
    _text("user", "we should switch the cache to copy-on-write"),
    _text("assistant", "Agreed, that removes the invalidation race."),
]


def _wait(manager, timeout=30):
    thread = manager._last_flush_thread
    assert thread is not None, "no flush thread was dispatched"
    thread.join(timeout=timeout)
    assert not thread.is_alive(), "the flush worker did not finish"


def _daily_files(workspace):
    return sorted(workspace.glob("memory/*.md"))


def test_a_day_whose_flush_never_landed_stays_retryable(tmp_path):
    # RED on unfixed code: the hash is spent on dispatch, so the second call
    # deduplicates against a day that was never written.
    manager = _NoSummaryManager(tmp_path, _UnreachableModel())

    assert manager.create_daily_summary(_TODAY) is True
    _wait(manager)

    assert manager._last_flushed_content_hash == "", (
        "a failed flush must not consume the day"
    )
    assert _daily_files(tmp_path) == []


def test_the_day_is_recovered_once_the_provider_returns(tmp_path):
    # The point of not spending the hash: the retry actually persists it.
    manager = _FlakyNoSummaryManager(tmp_path, _FlakyModel())

    assert manager.create_daily_summary(_TODAY) is True
    _wait(manager)
    assert _daily_files(tmp_path) == [], "the first attempt failed"

    manager.recover()

    # Second tick, same day, same content -- must be dispatched, not skipped.
    assert manager.create_daily_summary(_TODAY) is True
    _wait(manager)

    files = _daily_files(tmp_path)
    assert files, "the retry must write the daily file"
    assert "copy-on-write" in files[0].read_text(encoding="utf-8")


def test_a_day_that_landed_is_still_deduplicated(tmp_path):
    # The success path must not regress into re-summarising every tick.
    manager = MemoryFlushManager(tmp_path, _StubModel())

    assert manager.create_daily_summary(_TODAY) is True
    _wait(manager)

    first = _daily_files(tmp_path)
    assert len(first) == 1
    assert manager._last_flushed_content_hash != ""

    assert manager.create_daily_summary(_TODAY) is False, (
        "a day that already landed must not be summarised again"
    )
    assert _daily_files(tmp_path) == first


def test_an_inflight_day_is_not_submitted_twice(tmp_path):
    # The claim also holds a re-entrant call at bay, matching what the
    # per-message hashes already do.
    import threading

    entered = threading.Event()
    release = threading.Event()

    class _BlockingModel:
        def __init__(self):
            self.calls = 0

        def call(self, request):
            self.calls += 1
            entered.set()
            if not release.wait(30):
                raise TimeoutError("test never released the flush")
            return {"choices": [{"message": {"content": SUMMARY}}]}

    model = _BlockingModel()
    manager = MemoryFlushManager(tmp_path, model)

    assert manager.create_daily_summary(_TODAY) is True
    assert entered.wait(30), "the flush never reached the model"

    # Same content while the first is still running: deduplicated, not doubled.
    assert manager.create_daily_summary(_TODAY) is False
    assert model.calls == 1

    release.set()
    _wait(manager)
    assert len(_daily_files(tmp_path)) == 1


def test_a_model_that_records_nothing_still_closes_the_day(tmp_path):
    # "Nothing worth recording" is an answer, not a failure -- same rule the
    # per-message hashes follow, so the day is not re-billed every tick.
    manager = MemoryFlushManager(tmp_path, _StubModel(content="<nothing worth recording>"))

    assert manager.create_daily_summary(_TODAY) is True
    _wait(manager)

    assert manager.create_daily_summary(_TODAY) is False
    assert manager._last_flushed_content_hash != ""


def test_a_failed_write_hands_the_day_back(tmp_path):
    # The other failure mode: the model answered but the disk did not take it.
    manager = MemoryFlushManager(tmp_path, _StubModel())

    def flaky_write(summary, **kwargs):
        return False

    manager.write_daily_summary = flaky_write

    assert manager.create_daily_summary(_TODAY) is True
    _wait(manager)

    assert manager._last_flushed_content_hash == "", (
        "a write that failed must not close the day"
    )


def test_new_content_on_the_same_day_is_a_new_day(tmp_path):
    # Two different conversations on one calendar day must both be summarised;
    # a single remembered hash cannot tell them apart.
    manager = MemoryFlushManager(tmp_path, _StubModel())
    later = [
        _text("user", "one more thing: move the metrics into their own table"),
        _text("assistant", "Noted."),
    ]

    assert manager.create_daily_summary(_TODAY) is True
    _wait(manager)
    assert manager.create_daily_summary(later) is True, (
        "different content must not deduplicate against the earlier day"
    )
    _wait(manager)


def test_the_legacy_hash_attribute_is_still_written(tmp_path):
    # _last_flushed_content_hash is read elsewhere in the memory subsystem;
    # it must keep tracking the last day that landed.
    manager = MemoryFlushManager(tmp_path, _StubModel())

    assert manager._last_flushed_content_hash == ""
    manager.create_daily_summary(_TODAY)
    _wait(manager)
    assert manager._last_flushed_content_hash != ""


def test_a_failed_day_leaves_no_inflight_claim_behind(tmp_path):
    # Otherwise the day would be stuck in the inflight set and never
    # dispatchable again -- the same loss in a new shape.
    manager = _NoSummaryManager(tmp_path, _UnreachableModel())

    manager.create_daily_summary(_TODAY)
    _wait(manager)

    inflight = getattr(manager, "_daily_inflight_hashes", set())
    assert not inflight, "a failed day must not stay claimed"


@pytest.mark.parametrize("reason", ["trim", "overflow"])
def test_a_trim_flush_does_not_touch_the_day_ledger(tmp_path, reason):
    # The day-level sets belong to create_daily_summary only; a trim must not
    # commit or release a day hash it was never given.
    manager = MemoryFlushManager(tmp_path, _StubModel())

    assert manager.flush_from_messages(_TODAY, reason=reason) is True
    _wait(manager)

    # Read through getattr so this asserts the observable contract rather
    # than the presence of the bookkeeping attribute.
    assert not getattr(manager, "_daily_inflight_hashes", set())
    assert not getattr(manager, "_daily_flushed_hashes", set())
    assert manager._last_flushed_content_hash == ""
