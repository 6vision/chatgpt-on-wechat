"""Temporal decay should only apply to daily diary files (memory/YYYY-MM-DD.md).

Dated knowledge pages, handoff notes and any other date-suffixed markdown live
outside ``memory/`` must stay evergreen, otherwise their retrieval scores are
silently discounted as if they were perishable daily logs.
"""

from agent.memory.manager import MemoryManager


def _decay(path: str) -> float:
    return MemoryManager._compute_temporal_decay(path)


class TestDecayScope:
    """Anchor: only ``memory/YYYY-MM-DD.md`` decays."""

    def test_dated_knowledge_page_stays_evergreen(self):
        # knowledge/analysis/foo-2026-09-02.md ends in a date but is NOT a
        # daily diary -> must not decay.
        assert _decay("knowledge/analysis/cursor-spacex-2026-08-29.md") == 1.0

    def test_dated_source_page_stays_evergreen(self):
        assert _decay("knowledge/sources/folotoy-ai-passport-2026-09-27.md") == 1.0

    def test_handoff_note_stays_evergreen(self):
        # memory/handoff-2026-09-12-foo.md is under memory/ but is not a
        # daily diary (date is not immediately after memory/).
        assert _decay("memory/handoff-2026-09-12-memory-decay-scope.md") == 1.0

    def test_plain_file_stays_evergreen(self):
        assert _decay("memory/MEMORY.md") == 1.0
        assert _decay("README.md") == 1.0

    def test_old_daily_diary_decays(self):
        # A diary dated far in the past must be discounted.
        assert _decay("memory/2025-01-01.md") < 1.0

    def test_per_user_and_dream_diaries_decay(self):
        assert _decay("memory/users/u-1/2025-01-01.md") < 1.0
        assert _decay("memory/dreams/2025-01-01.md") < 1.0
        assert _decay("memory/users/u-1/handoff-2025-01-01.md") == 1.0

    def test_today_diary_is_evergreen(self):
        import datetime

        today = datetime.date.today().strftime("%Y-%m-%d")
        assert _decay(f"memory/{today}.md") == 1.0

    def test_backslash_path_is_normalized(self):
        # Windows checkout residue: backslashes must not break the anchor.
        assert _decay(r"memory\2025-01-01.md") < 1.0
        assert _decay(r"knowledge\analysis\foo-2026-09-02.md") == 1.0

    def test_half_life_parameter_is_respected(self):
        # Same file, longer half-life -> slower decay (larger multiplier).
        short = MemoryManager._compute_temporal_decay("memory/2025-01-01.md", half_life_days=1.0)
        long = MemoryManager._compute_temporal_decay("memory/2025-01-01.md", half_life_days=365.0)
        assert short < long
        assert short < 1.0
        assert long < 1.0
