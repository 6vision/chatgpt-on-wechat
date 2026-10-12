"""Regression: a task whose stored `schedule` is not a mapping must not raise.

`task.get("schedule", {})` only substitutes the default when the key is absent.
A key present with a null or a bare string left None in place, and the chained
`.get("timezone")` raised AttributeError from every scheduler read path."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools.scheduler.time_utils import (  # noqa: E402
    normalize_task_timestamps,
    scheduled_reference_time,
    task_timezone,
)


class TestTaskTimezoneToleratesANonMappingSchedule:
    def test_a_null_schedule_is_legacy_mode_not_a_crash(self):
        assert task_timezone({"schedule": None}) is None

    def test_a_string_schedule_is_legacy_mode_not_a_crash(self):
        assert task_timezone({"schedule": "daily"}) is None

    def test_a_list_or_number_schedule_is_legacy_mode_not_a_crash(self):
        for bad in ([], 0, 3.5, True):
            assert task_timezone({"schedule": bad}) is None

    def test_an_absent_schedule_is_still_legacy_mode(self):
        assert task_timezone({}) is None

    def test_a_real_timezone_is_still_honoured(self):
        zone = task_timezone({"schedule": {"type": "cron", "timezone": "UTC"}})
        assert zone is not None
        assert getattr(zone, "key", str(zone)) == "UTC"

    def test_normalize_task_timestamps_survives_a_null_schedule(self):
        # This is the call the scheduler loop makes for every task on every tick.
        task = {"id": "t1", "schedule": None,
                "next_run_at": "2099-01-01T09:00:00"}
        out = normalize_task_timestamps(task)
        assert out["next_run_at"] == "2099-01-01T09:00:00"

    def test_scheduled_reference_time_survives_a_null_schedule(self):
        now = datetime(2099, 1, 1, 9, 0, 0)
        out = scheduled_reference_time({"schedule": None}, now)
        assert isinstance(out, datetime)

    def test_a_zoned_task_still_normalizes_to_utc(self):
        task = {"id": "t1", "schedule": {"type": "cron", "timezone": "UTC"},
                "next_run_at": "2099-01-01T09:00:00+00:00"}
        out = normalize_task_timestamps(task)
        parsed = datetime.fromisoformat(out["next_run_at"])
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)
        assert parsed == datetime(2099, 1, 1, 9, 0, tzinfo=timezone.utc)
