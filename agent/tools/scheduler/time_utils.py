"""Time helpers for scheduler persistence and recurrence.

Tasks that explicitly declare an IANA timezone use timezone-aware UTC
timestamps, and their cron recurrences are evaluated with full DST rules.
Tasks without a declared timezone intentionally keep the scheduler's legacy
naive local-time behaviour so existing stored tasks are not reinterpreted.
"""
from croniter import croniter
from datetime import datetime, timedelta, timezone

# zoneinfo joined the standard library in Python 3.9. Without it, only named
# IANA timezones are unavailable; legacy naive-local tasks keep working.
try:
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None

UTC = timezone.utc

# Fields whose persisted values are scheduling instants. Other metadata such
# as created_at/updated_at is not needed by the comparison path and is left
# alone for compatibility with external editors.
SCHEDULE_TIMESTAMP_FIELDS = (
    "next_run_at",
    "last_run_at",
    "last_error_at",
    "last_manual_run_at",
)


def utc_now() -> datetime:
    """Return the current instant in UTC."""
    return datetime.now(UTC)


def resolve_timezone(name=None):
    """Resolve an optional IANA name, defaulting to the server-local zone.

    Prefer :func:`task_timezone` for scheduler tasks.  Scheduler tasks use a
    ``None`` return value as an explicit signal that they must stay on the
    legacy naive-local code path.
    """
    if name is None:
        return datetime.now().astimezone().tzinfo
    if not isinstance(name, str) or not name.strip():
        raise ValueError("timezone must be a non-empty IANA name")
    if ZoneInfo is None:
        raise ValueError(
            "IANA timezones require Python 3.9+ or the backports.zoneinfo package"
        )
    return ZoneInfo(name.strip())


def task_timezone(task: dict):
    """Return the IANA zone declared by a task, or ``None`` for legacy mode."""
    name = task.get("schedule", {}).get("timezone")
    return resolve_timezone(name) if name else None


def _parse_iso(value: str) -> datetime:
    """Parse an ISO timestamp and normalize a trailing ``Z`` suffix."""
    if not isinstance(value, str):
        raise TypeError("timestamp must be an ISO string")

    # datetime.fromisoformat accepts "Z" from Python 3.11; normalize it here
    # so the scheduler keeps working on the versions supported by the project.
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def parse_utc(value: str, default_zone=None) -> datetime:
    """Parse a timestamp used by an IANA-timezone task as aware UTC."""
    dt = _parse_iso(value)
    if dt.tzinfo is None:
        if default_zone is None:
            raise ValueError("a timezone is required for a naive timestamp")
        dt = dt.replace(tzinfo=default_zone)
    return dt.astimezone(UTC)


def parse_scheduled_time(value: str, zone=None) -> datetime:
    """Parse a task timestamp in either UTC-aware or legacy-naive mode.

    With an explicit IANA zone, naive values are interpreted in that zone and
    the result is normalized to UTC.  Without one, naive values remain naive;
    an already-aware value is compared as the equivalent local wall clock.
    """
    dt = _parse_iso(value)
    if zone is not None:
        return parse_utc(value, zone)
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def format_scheduled_time(value: datetime) -> str:
    """Serialize a UTC-aware instant or a legacy naive local timestamp."""
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(UTC).isoformat()


def format_utc(value: datetime) -> str:
    """Format an aware datetime as an aware UTC ISO string."""
    return value.astimezone(UTC).isoformat()


def normalize_task_timestamps(task: dict) -> dict:
    """Normalize scheduling fields in a task copy for scheduler reads.

    Explicit-IANA-zone tasks use aware UTC strings.  Legacy tasks are returned
    unchanged on upgrade: interpreting their naive timestamps with a fixed
    local offset would change their meaning across DST transitions.
    """
    zone = task_timezone(task)
    if zone is None:
        return dict(task)

    normalized = dict(task)
    for field in SCHEDULE_TIMESTAMP_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = format_utc(parse_utc(value, zone))
    return normalized


def scheduled_reference_time(task: dict, value: datetime) -> datetime:
    """Coerce a current/reference time to the task's comparison mode."""
    if task_timezone(task) is not None:
        # A naive server-local reference is sufficient for computing "now";
        # astimezone() attaches the local offset before converting to UTC.
        return value.astimezone(UTC)
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def _localize_wall_time(naive_dt: datetime, zone) -> datetime:
    """Attach a zone to a local wall clock with explicit DST policies.

    Fall-back times use the first occurrence (``fold=0``), so a daily task does
    not run twice. Spring-forward gaps advance minute by minute to the next
    real local time. Aware croniter input can otherwise manufacture an offset
    for a wall time that never exists.
    """
    candidate = naive_dt.replace(tzinfo=zone)
    instant = candidate.astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) == naive_dt:
        return instant

    for _ in range(120):  # enough for the largest civil-time gap
        naive_dt += timedelta(minutes=1)
        candidate = naive_dt.replace(tzinfo=zone)
        instant = candidate.astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == naive_dt:
            return instant
    raise ValueError("could not resolve local time across a DST transition")


def next_cron_occurrence(expression: str, after: datetime, zone=None) -> datetime:
    """Evaluate cron wall-clock recurrence in the task's scheduling mode."""
    if zone is None:
        if after.tzinfo is not None:
            after = after.astimezone().replace(tzinfo=None)
        return croniter(expression, after).get_next(datetime)

    after_utc = after.astimezone(UTC) if after.tzinfo is not None else after
    local_after = after_utc.astimezone(zone).replace(tzinfo=None)
    local_next = croniter(expression, local_after).get_next(datetime)
    instant = _localize_wall_time(local_next, zone).astimezone(UTC)
    if instant <= after_utc:
        # During a fall-back fold, croniter can return an occurrence in
        # the first fold that maps to an instant already past.  Retry.
        local_next = croniter(expression, local_after + timedelta(minutes=1)).get_next(datetime)
        instant = _localize_wall_time(local_next, zone).astimezone(UTC)
    return instant


def display_local(value: str, zone=None) -> datetime:
    """Convert a persisted scheduling timestamp for display.

    Explicit-IANA-zone tasks are displayed in that zone.  Legacy tasks show
    their stored wall clock directly; an aware legacy value is displayed in the
    viewer's local zone because it already identifies a concrete instant.
    """
    dt = parse_scheduled_time(value, zone)
    if dt.tzinfo is None:
        return dt
    if zone is not None:
        return dt.astimezone(zone)
    return dt.astimezone()
