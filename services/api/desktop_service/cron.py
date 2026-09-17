"""Minimal five-field cron (minute hour day-of-month month day-of-week) with IANA time zones.

Supports *, numbers, ranges (a-b), steps (*/n, a-b/n) and lists. Day-of-month and day-of-week follow
the classic rule: when both are restricted, a time matches if either matches. Sunday is 0 or 7.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FIELDS = [("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31), ("month", 1, 12), ("weekday", 0, 7)]
NAMES = {
    "month": {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)},
    "weekday": {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())},
}


class CronError(ValueError):
    pass


def _value(token, field, low, high):
    token = token.lower()
    number = NAMES.get(field, {}).get(token)
    if number is None:
        if not token.isdigit():
            raise CronError(f"Invalid {field} value {token!r}")
        number = int(token)
    if not low <= number <= high:
        raise CronError(f"{field} value {number} is outside {low}-{high}")
    return number


def _field(text, field, low, high):
    values = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"Empty {field} list item")
        base, _, step = part.partition("/")
        step_value = 1
        if step:
            if not step.isdigit() or int(step) == 0:
                raise CronError(f"Invalid {field} step {step!r}")
            step_value = int(step)
        if base == "*":
            start, end = low, high
        elif "-" in base:
            a, b = base.split("-", 1)
            start, end = _value(a, field, low, high), _value(b, field, low, high)
            if start > end:
                raise CronError(f"Reversed {field} range {base!r}")
        else:
            start = _value(base, field, low, high)
            end = high if step else start
        values.update(range(start, end + 1, step_value))
    if field == "weekday" and 7 in values:
        values.discard(7)
        values.add(0)
    return values


class Cron:
    def __init__(self, expression, tz="UTC"):
        parts = expression.split()
        if len(parts) != 5:
            raise CronError("Cron needs five fields: minute hour day-of-month month day-of-week")
        try:
            self.zone = ZoneInfo(tz)
        except Exception:
            raise CronError(f"Unknown time zone {tz!r}") from None
        self.expression = expression
        self.minute, self.hour, self.day, self.month, self.weekday = (
            _field(text, name, low, high) for text, (name, low, high) in zip(parts, FIELDS, strict=True)
        )
        self.day_restricted = parts[2] != "*"
        self.weekday_restricted = parts[4] != "*"

    def matches(self, local):
        if local.minute not in self.minute or local.hour not in self.hour or local.month not in self.month:
            return False
        day_ok = local.day in self.day
        weekday_ok = (local.isoweekday() % 7) in self.weekday
        if self.day_restricted and self.weekday_restricted:
            return day_ok or weekday_ok
        return day_ok and weekday_ok

    def next_after(self, moment):
        """Next matching minute strictly after `moment` (naive UTC in, naive UTC out)."""
        local = moment.replace(tzinfo=timezone.utc).astimezone(self.zone).replace(second=0, microsecond=0)
        local += timedelta(minutes=1)
        # Four years of minutes covers every valid expression, including Feb 29.
        for _ in range(4 * 366 * 24 * 60):
            if local.month not in self.month:
                local = (local.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
                continue
            if local.hour not in self.hour:
                local = local.replace(minute=0) + timedelta(hours=1)
                continue
            if self.matches(local):
                return local.astimezone(timezone.utc).replace(tzinfo=None)
            local += timedelta(minutes=1)
        raise CronError("Expression never matches")

    def minimum_gap_minutes(self, start=None, samples=6):
        """Smallest spacing between consecutive fire times observed over a short horizon."""
        moment = start or datetime(2026, 1, 5)
        times = []
        for _ in range(samples):
            moment = self.next_after(moment)
            times.append(moment)
        return min((b - a).total_seconds() / 60 for a, b in zip(times, times[1:], strict=False))
