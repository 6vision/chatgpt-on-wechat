"""Cron recurrence must advance beyond an already elapsed first DST fold."""

from datetime import datetime, timezone

import pytest

from agent.tools.scheduler.scheduler_service import SchedulerService


@pytest.mark.parametrize(
    "zone, expression, reference, expected",
    [
        (
            "America/New_York",
            "30 1 * * *",
            "2026-11-01T06:15:00+00:00",
            "2026-11-02T06:30:00+00:00",
        ),
        (
            "America/New_York",
            "* * * * *",
            "2026-11-01T06:15:00+00:00",
            "2026-11-01T07:00:00+00:00",
        ),
        (
            "Australia/Lord_Howe",
            "45 1 * * *",
            "2026-04-04T15:05:00+00:00",
            "2026-04-05T15:15:00+00:00",
        ),
    ],
)
def test_second_fold_skips_every_elapsed_first_fold_occurrence(zone, expression, reference, expected):
    task = {"schedule": {"type": "cron", "expression": expression, "timezone": zone}}
    after = datetime.fromisoformat(reference)

    result = SchedulerService.__new__(SchedulerService)._calculate_next_run(task, after)

    assert result is not None
    assert result > after
    assert result == datetime.fromisoformat(expected).astimezone(timezone.utc)
