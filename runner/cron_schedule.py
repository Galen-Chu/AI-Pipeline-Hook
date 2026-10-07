"""
Minimal cron schedule utilities for pipeline trigger.schedule
(5-field cron: minute hour day-of-month month day-of-week).

Supported syntax per field: *  */n  a  a-b  a-b/n  a,b,c
dow 0 and 7 both mean Sunday. When both dom and dow are restricted
(neither is *), a day matching either one qualifies (standard cron
OR-semantics). Schedules are evaluated in local time.
"""
from datetime import datetime, timedelta

FIELD_RANGES = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("dom", 1, 31),
    ("month", 1, 12),
    ("dow", 0, 7),
)

_FULL = {
    "minute": set(range(0, 60)),
    "hour": set(range(0, 24)),
    "dom": set(range(1, 32)),
    "month": set(range(1, 13)),
    "dow": set(range(0, 7)),  # after 7→0 normalization
}

SEARCH_WINDOW_DAYS = 8


def _parse_field(field: str, low: int, high: int, normalize_dow: bool) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty part in cron field '{field}'")

        step = 1
        if "/" in part:
            part, step_str = part.split("/", 1)
            step = int(step_str)
            if step < 1:
                raise ValueError(f"invalid step in cron field '{field}'")

        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            v = int(part)
            if step > 1:  # Vixie semantics: "5/15" ≡ "5-high/15"
                start, end = v, high
            else:
                start = end = v

        if not (low <= start <= high and low <= end <= high and start <= end):
            raise ValueError(f"cron field out of range: '{field}'")
        for v in range(start, end + 1, step):
            if normalize_dow and v == 7:
                v = 0
            values.add(v)
    return values


def parse_cron(expr: str) -> dict[str, set[int]]:
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron expression must have 5 fields, got {len(fields)}: '{expr}'")
    spec = {}
    for value, (name, low, high) in zip(fields, FIELD_RANGES):
        spec[name] = _parse_field(value, low, high, normalize_dow=(name == "dow"))
    return spec


def _cron_dow(dt: datetime) -> int:
    return (dt.weekday() + 1) % 7  # cron dow: 0=Sun … 6=Sat


def _day_matches(spec: dict[str, set[int]], day: datetime) -> bool:
    if day.month not in spec["month"]:
        return False
    dom_ok = day.day in spec["dom"]
    dow_ok = _cron_dow(day) in spec["dow"]
    dom_restricted = spec["dom"] != _FULL["dom"]
    dow_restricted = spec["dow"] != _FULL["dow"]
    if dom_restricted and dow_restricted:
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def matches(spec: dict[str, set[int]], dt: datetime) -> bool:
    """Whether a naive local datetime satisfies the parsed cron spec."""
    return (dt.minute in spec["minute"] and dt.hour in spec["hour"]
            and _day_matches(spec, dt))


def _latest_time_on_day(spec: dict[str, set[int]], no_later_than: datetime) -> datetime | None:
    for hour in sorted(spec["hour"], reverse=True):
        if hour > no_later_than.hour:
            continue
        for minute in sorted(spec["minute"], reverse=True):
            if hour == no_later_than.hour and minute > no_later_than.minute:
                continue
            return no_later_than.replace(hour=hour, minute=minute)
    return None


def last_fire_time(expr: str, now: datetime) -> datetime | None:
    """Most recent scheduled time <= now (minute resolution, local time).

    Returns None when nothing matches within the search window.
    """
    spec = parse_cron(expr)
    minute_floor = now.replace(second=0, microsecond=0)
    for day_offset in range(SEARCH_WINDOW_DAYS):
        day = minute_floor - timedelta(days=day_offset)
        if not _day_matches(spec, day):
            continue
        limit = day if day_offset == 0 else day.replace(hour=23, minute=59)
        fire = _latest_time_on_day(spec, limit)
        if fire is not None:
            return fire
    return None


def is_due(expr: str, last_run: str | None, now: datetime) -> bool:
    """A pipeline is due when a scheduled fire time exists that the last
    run predates (never run ⇒ due as soon as the first fire time passes).
    Aware datetimes are compared in local naive time."""
    fire = last_fire_time(expr, now)
    if fire is None:
        return False
    if fire.tzinfo is not None:
        fire = fire.astimezone().replace(tzinfo=None)
    if not last_run:
        return True
    last = datetime.fromisoformat(last_run)
    if last.tzinfo is not None:
        last = last.astimezone().replace(tzinfo=None)
    return last < fire
