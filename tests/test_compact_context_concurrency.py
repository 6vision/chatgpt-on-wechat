"""Compaction keeps a turn that lands while the summary is being produced."""

import sys
import threading
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.protocol.agent import Agent


def _q(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _a(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


class _SlowFlush:
    """Summarize blocks until ``release`` so a turn can land mid-compaction."""

    def __init__(self, entered, release):
        self.entered = entered
        self.release = release

    def _summarize_messages(self, messages, max_messages=0):
        self.entered.set()
        assert self.release.wait(timeout=5), "summarize was never released"
        return "SUMMARY"

    def _clean_summary_output(self, raw):
        return raw

    def write_daily_summary(self, *args, **kwargs):
        pass


def _agent(history):
    agent = Agent.__new__(Agent)
    agent.messages = list(history)
    agent.messages_lock = threading.RLock()
    agent.last_usage = None
    entered, release = threading.Event(), threading.Event()
    release.set()  # by default the summarize returns at once
    agent.memory_manager = types.SimpleNamespace(
        flush_manager=_SlowFlush(entered, release)
    )
    return agent, (entered, release)


def _run_with_concurrent_write(agent, events, new_messages):
    """Append ``new_messages`` to the history while compaction is summarizing."""
    entered, release = events
    release.clear()

    def worker():
        assert entered.wait(timeout=5), "compaction never reached the summarize step"
        with agent.messages_lock:
            agent.messages = agent.messages + list(new_messages)
        release.set()

    thread = threading.Thread(target=worker)
    thread.start()
    return thread


def _texts(messages):
    out = []
    for message in messages:
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict):
                out.append(block.get("text", ""))
    return out


class CompactContextConcurrencyTest(unittest.TestCase):
    HISTORY = [_q("q1"), _a("a1"), _q("q2"), _a("a2"), _q("q3"), _a("a3")]

    def test_a_turn_that_lands_mid_compaction_is_kept(self):
        agent, events = _agent(self.HISTORY)
        worker = _run_with_concurrent_write(agent, events, [_q("q4"), _a("a4")])
        result = agent.compact_context(keep_recent_turns=1)
        worker.join(timeout=5)

        texts = _texts(agent.messages)
        self.assertEqual(result.get("compacted_turns"), 2)
        self.assertIn("q4", texts)
        self.assertIn("a4", texts)
        self.assertTrue(any("SUMMARY" in t for t in texts), texts)
        self.assertNotIn("q1", texts)

    def test_an_untouched_history_compacts_exactly_as_before(self):
        agent, _ = _agent(self.HISTORY)
        result = agent.compact_context(keep_recent_turns=1)

        self.assertEqual(result, {
            "ok": True, "reason": "compacted", "compacted_turns": 2,
            "before": 6, "after": 2,
        })
        texts = _texts(agent.messages)
        self.assertTrue(any("SUMMARY" in t for t in texts), texts)
        self.assertEqual(len(agent.messages), 2)

    def test_a_history_rewritten_underneath_is_reported_not_overwritten(self):
        agent, events = _agent(self.HISTORY)
        entered, release = events
        release.clear()

        def concurrent_trim():
            assert entered.wait(timeout=5)
            with agent.messages_lock:
                agent.messages = [_q("trimmed")]
            release.set()

        worker = threading.Thread(target=concurrent_trim)
        worker.start()
        result = agent.compact_context(keep_recent_turns=1)
        worker.join(timeout=5)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "history_changed")
        self.assertEqual(_texts(agent.messages), ["trimmed"])


if __name__ == "__main__":
    unittest.main()