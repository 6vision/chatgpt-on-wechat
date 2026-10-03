# encoding:utf-8
"""
Regression tests for the Self-Evolution tab's file ordering.

The unified "Self-Evolution" list merges `memory/evolution/YYYY-MM-DD.md` with
the nightly `memory/dreams/YYYY-MM-DD.md` diary, and both are written per day,
so the same filename legitimately appears twice. The sort key documented "ties
favor evolution", but the tie-break boolean was inverted: with `reverse=True`
the larger key wins, and `type != "evolution"` is larger for a dream entry, so
the dream diary was listed above the evolution log it is supposed to sit behind.

The tab is what the web console's memory page renders, so on any day the agent
both dreamt and evolved, the reader was shown the dream before the evolution
record for that day.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.service import MemoryService


class TestEvolutionListOrder(unittest.TestCase):
    """Same-day entries list the evolution log first; distinct days still sort
    newest first."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.service = MemoryService(str(self.root))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # -- helpers -------------------------------------------------------

    def _write(self, sub, name):
        target = self.root / "memory" / sub
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(f"# {sub} {name}\n", encoding="utf-8")

    def _evolution_tab(self):
        listing = self.service.list_files(category="evolution")["list"]
        return [(entry["filename"], entry["type"]) for entry in listing]

    # -- tests ---------------------------------------------------------

    def test_a_same_day_dream_diary_does_not_outrank_the_evolution_log(self):
        self._write("evolution", "2026-02-20.md")
        self._write("dreams", "2026-02-20.md")

        self.assertEqual(
            self._evolution_tab(),
            [("2026-02-20.md", "evolution"), ("2026-02-20.md", "dream")],
        )

    def test_ties_prefer_evolution_while_dates_stay_newest_first(self):
        self._write("evolution", "2026-02-19.md")
        self._write("evolution", "2026-02-20.md")
        self._write("dreams", "2026-02-19.md")
        self._write("dreams", "2026-02-20.md")

        self.assertEqual(
            self._evolution_tab(),
            [
                ("2026-02-20.md", "evolution"),
                ("2026-02-20.md", "dream"),
                ("2026-02-19.md", "evolution"),
                ("2026-02-19.md", "dream"),
            ],
        )

    def test_untied_dates_are_unaffected(self):
        self._write("dreams", "2026-02-21.md")
        self._write("evolution", "2026-02-20.md")
        self._write("dreams", "2026-02-18.md")

        self.assertEqual(
            self._evolution_tab(),
            [
                ("2026-02-21.md", "dream"),
                ("2026-02-20.md", "evolution"),
                ("2026-02-18.md", "dream"),
            ],
        )

    def test_both_files_are_still_reachable_after_listing(self):
        # Ordering decides which of the two same-named entries is shown first,
        # not whether the other one is listed — get_content resolves each by its
        # own directory, so a reader must still be able to open the dream.
        self._write("evolution", "2026-02-20.md")
        self._write("dreams", "2026-02-20.md")

        evolution = self.service.get_content("2026-02-20.md", category="evolution")
        dream = self.service.get_content("2026-02-20.md", category="dream")

        self.assertEqual(evolution["rel_path"], "memory/evolution/2026-02-20.md")
        self.assertEqual(dream["rel_path"], "memory/dreams/2026-02-20.md")


if __name__ == "__main__":
    unittest.main()
