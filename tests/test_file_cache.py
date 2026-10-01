# encoding:utf-8
"""
Unit tests for the channel/file_cache.py TTL.

A session's cache is one batch: files are added silently as they arrive and are
attached to the user's next text message (see channel/dingtalk/dingtalk_channel.py).
The window therefore has to run from the most recent file of the batch rather
than from the first one, or a burst spanning more than the TTL loses its tail —
including files that arrived seconds before the question.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.file_cache import FileCache


class TestFileCacheTtl(unittest.TestCase):
    def _clock(self, start=1000.0):
        """A controllable clock, so no test ever has to sleep."""
        return {"now": start}

    def test_ttl_runs_from_the_most_recent_file(self):
        """A batch spread over more than the TTL still arrives whole."""
        cache = FileCache(ttl=300)
        clock = self._clock()
        with patch("channel.file_cache.time.time", side_effect=lambda: clock["now"]):
            cache.add("s1", "/tmp/a.png", "image")
            clock["now"] += 240  # 4 min later: still inside the window
            cache.add("s1", "/tmp/b.png", "image")
            clock["now"] += 240  # 4 min after b, 8 min after a
            files = cache.get("s1")

        self.assertEqual([f["path"] for f in files], ["/tmp/a.png", "/tmp/b.png"])

    def test_cache_still_expires_when_nothing_new_arrives(self):
        """Refreshing on every add must not turn the TTL into "never expires"."""
        cache = FileCache(ttl=300)
        clock = self._clock()
        with patch("channel.file_cache.time.time", side_effect=lambda: clock["now"]):
            cache.add("s1", "/tmp/a.png", "image")
            clock["now"] += 301
            files = cache.get("s1")

        self.assertEqual(files, [])

    def test_new_file_after_expiry_starts_a_fresh_batch(self):
        """A new upload must not revive attachments from an expired batch."""
        cache = FileCache(ttl=300)
        clock = self._clock()
        with patch("channel.file_cache.time.time", side_effect=lambda: clock["now"]):
            cache.add("s1", "/tmp/old.pdf", "file")
            clock["now"] += 301
            cache.add("s1", "/tmp/new.png", "image")
            files = cache.get("s1")

        self.assertEqual(files, [{"path": "/tmp/new.png", "type": "image"}])

    def test_re_adding_after_expiry_does_not_revive_other_files(self):
        cache = FileCache(ttl=300)
        clock = self._clock()
        with patch("channel.file_cache.time.time", side_effect=lambda: clock["now"]):
            cache.add("s1", "/tmp/a.png", "image")
            cache.add("s1", "/tmp/b.pdf", "file")
            clock["now"] += 301
            cache.add("s1", "/tmp/a.png", "image")
            files = cache.get("s1")

        self.assertEqual(files, [{"path": "/tmp/a.png", "type": "image"}])

    def test_upload_at_ttl_boundary_preserves_the_batch(self):
        """Match get() and cleanup_expired(): expiry is strictly after TTL."""
        cache = FileCache(ttl=300)
        clock = self._clock()
        with patch("channel.file_cache.time.time", side_effect=lambda: clock["now"]):
            cache.add("s1", "/tmp/a.png", "image")
            clock["now"] += 300
            cache.add("s1", "/tmp/b.png", "image")
            files = cache.get("s1")

        self.assertEqual([f["path"] for f in files], ["/tmp/a.png", "/tmp/b.png"])

    def test_re_adding_the_same_file_refreshes_the_window(self):
        """Re-sending a file is still activity on that batch."""
        cache = FileCache(ttl=300)
        clock = self._clock()
        with patch("channel.file_cache.time.time", side_effect=lambda: clock["now"]):
            cache.add("s1", "/tmp/a.png", "image")
            clock["now"] += 240
            cache.add("s1", "/tmp/a.png", "image")  # duplicate, deduped
            clock["now"] += 240
            files = cache.get("s1")

        self.assertEqual([f["path"] for f in files], ["/tmp/a.png"])

    def test_cleanup_expired_uses_the_refreshed_timestamp(self):
        cache = FileCache(ttl=300)
        clock = self._clock()
        with patch("channel.file_cache.time.time", side_effect=lambda: clock["now"]):
            cache.add("s1", "/tmp/a.png", "image")
            clock["now"] += 240
            cache.add("s1", "/tmp/b.png", "image")
            clock["now"] += 240  # 4 min past the last file
            cache.cleanup_expired()
            self.assertIn("s1", cache.cache)

            clock["now"] += 61  # 5 min 1 s past the last file
            cache.cleanup_expired()
            self.assertNotIn("s1", cache.cache)


if __name__ == "__main__":
    unittest.main()
