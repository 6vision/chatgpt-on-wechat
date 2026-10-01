"""A summary flush that never reached the disk must stay retryable.

A trim or overflow hands the discarded turns to a daemon thread and then drops
them from the working context no matter what the flush did. The dedup hash was
recorded on the calling thread, before the LLM had answered, so when the
provider was unreachable the hash was already spent: nothing was written to
``memory/YYYY-MM-DD.md`` and no later Deep Dream or search could ever recover
that window. These tests pin the hash to the outcome -- a failed flush leaves the
messages eligible, an in-flight flush is not submitted twice, and a flush that
did land is still deduplicated.
"""

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory.summarizer import MemoryFlushManager

SUMMARY = "- the user asked for the ingest split, and the schema stays frozen\n"


def _text(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


# A trim window that starts on an assistant turn -- its question fell outside the
# discarded slice, so the rule-based fallback has no event pair to record. If the
# LLM is unreachable this content produces no write at all, which is the window
# that used to be lost for good.
_LOST_WINDOW = [
    _text(
        "assistant",
        "Here is the migration plan we agreed on: split the ingest worker into "
        "its own process and keep the schema frozen until Q3.",
    ),
]

_PLAIN_WINDOW = [
    _text("user", "can you split the ingest worker out of the API process?"),
    _text("assistant", "Yes, it becomes a separate process with its own queue."),
]


class _StubModel:
    """Returns the shape ``_extract_response_text`` accepts (OpenAI format)."""

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


class _BlockingModel:
    """Holds the flush open so an in-flight dedup entry can be inspected."""

    def __init__(self, content: str = SUMMARY):
        self.content = content
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def call(self, request):
        self.calls += 1
        self.entered.set()
        if not self.release.wait(30):
            raise TimeoutError("test never released the flush")
        return {"choices": [{"message": {"content": self.content}}]}


def _wait(manager, timeout=30):
    """Join the dispatched worker instead of sleeping and hoping it finished."""
    thread = manager._last_flush_thread
    assert thread is not None, "no flush thread was dispatched"
    thread.join(timeout=timeout)
    assert not thread.is_alive(), "the flush worker did not finish"


def _daily_files(workspace):
    return sorted(workspace.glob("memory/*.md"))


def test_a_flush_that_wrote_nothing_can_be_retried(tmp_path):
    manager = MemoryFlushManager(tmp_path, _UnreachableModel())

    assert manager.flush_from_messages(_LOST_WINDOW) is True
    _wait(manager)
    assert _daily_files(tmp_path) == []

    # The caller has already dropped these turns from the working context, so a
    # second attempt is the only remaining chance to persist them.
    assert manager.flush_from_messages(_LOST_WINDOW) is True
    _wait(manager)
    assert _daily_files(tmp_path) == []


def test_the_retry_recovers_the_window_once_the_provider_returns(tmp_path):
    model = _FlakyModel()
    manager = MemoryFlushManager(tmp_path, model)

    assert manager.flush_from_messages(_LOST_WINDOW) is True
    _wait(manager)
    assert _daily_files(tmp_path) == []

    assert manager.flush_from_messages(_LOST_WINDOW) is True
    _wait(manager)

    assert model.calls == 2
    (written,) = _daily_files(tmp_path)
    assert "ingest split" in written.read_text(encoding="utf-8")


def test_a_flush_still_in_flight_is_not_submitted_twice(tmp_path):
    model = _BlockingModel()
    manager = MemoryFlushManager(tmp_path, model)

    assert manager.flush_from_messages(_PLAIN_WINDOW) is True
    assert model.entered.wait(30), "the worker never reached the model"
    try:
        # The first flush has not settled yet, so a second one for the same
        # turns would duplicate the summary.
        assert manager.flush_from_messages(_PLAIN_WINDOW) is False
    finally:
        model.release.set()
    _wait(manager)

    assert model.calls == 1
    (written,) = _daily_files(tmp_path)
    assert written.read_text(encoding="utf-8").count("## Trimmed Context") == 1


def test_a_written_flush_is_deduplicated(tmp_path):
    model = _StubModel()
    manager = MemoryFlushManager(tmp_path, model)

    assert manager.flush_from_messages(_PLAIN_WINDOW) is True
    _wait(manager)
    assert manager.flush_from_messages(_PLAIN_WINDOW) is False
    _wait(manager)

    assert model.calls == 1
    (written,) = _daily_files(tmp_path)
    assert written.read_text(encoding="utf-8").count("## Trimmed Context") == 1


def test_a_failed_write_can_be_retried(tmp_path, monkeypatch):
    manager = MemoryFlushManager(tmp_path, _StubModel())
    real_write = manager.write_daily_summary
    attempts = []

    def flaky_write(summary, **kwargs):
        attempts.append(summary)
        if len(attempts) == 1:
            return False
        return real_write(summary, **kwargs)

    monkeypatch.setattr(manager, "write_daily_summary", flaky_write)

    assert manager.flush_from_messages(_PLAIN_WINDOW) is True
    _wait(manager)
    assert _daily_files(tmp_path) == []

    monkeypatch.setattr(manager, "write_daily_summary", real_write)
    assert manager.flush_from_messages(_PLAIN_WINDOW) is True
    _wait(manager)

    (written,) = _daily_files(tmp_path)
    assert "ingest split" in written.read_text(encoding="utf-8")


@pytest.mark.parametrize("reply", ["无", "None"])
def test_a_model_that_records_nothing_is_not_asked_again(tmp_path, reply):
    """An answered "nothing worth recording" is a result, not a failure.

    Retrying it would re-bill the same LLM call for the same turns on every
    later trim, so this outcome stays deduplicated.
    """
    manager = MemoryFlushManager(tmp_path, _StubModel(reply))

    assert manager.flush_from_messages(_PLAIN_WINDOW) is True
    _wait(manager)

    assert manager.flush_from_messages(_PLAIN_WINDOW) is False
    assert _daily_files(tmp_path) == []
