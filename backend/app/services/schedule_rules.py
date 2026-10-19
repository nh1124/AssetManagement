"""Pure occurrence arithmetic. Every consumer uses the same inclusive dates."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from itertools import islice


def _month_due(year: int, month: int, day: int) -> date:
    return date(year, month, max(1, min(day, calendar.monthrange(year, month)[1])))


def occurrences(entry, on_or_after: date, through: date = date.max):
    """Yield scheduled dates, anchored at start_date, bounded by count/end_date.

    Month ends clamp independently, so February never shifts March's day.
    Seeking skips whole cycles without iterating years of old occurrences.
    """
    start = entry.start_date
    lower = max(start, on_or_after)
    upper = min(through, entry.end_date or date.max)
    if lower > upper:
        return
    if entry.repeat_mode == "once":
        if lower <= start <= upper:
            yield start
        return
    frequency = entry.frequency
    if frequency == "EveryNDays":
        days = entry.frequency_days
        if not days or days < 1:
            return
        first = start
        index = max(0, (lower - first).days // days)
        def at(i):
            return first + timedelta(days=days * i)
    elif frequency == "Yearly":
        month = entry.month_of_year or start.month
        day = entry.day_of_month or start.day
        year = start.year + (_month_due(start.year, month, day) < start)
        first = _month_due(year, month, day)
        index = max(0, lower.year - first.year)
        def at(i):
            return _month_due(first.year + i, month, day)
    elif frequency == "Monthly":
        day = entry.day_of_month or start.day
        base = start.year * 12 + start.month - 1
        if _month_due(start.year, start.month, day) < start:
            base += 1
        index = max(0, lower.year * 12 + lower.month - 1 - base)
        def at(i):
            year, month = divmod(base + i, 12)
            return _month_due(year, month + 1, day)
    else:
        return
    count = entry.repeat_count if entry.repeat_mode == "count" else None
    while count is None or index < count:
        try:
            candidate = at(index)
        except (OverflowError, ValueError):
            return
        if candidate > upper:
            return
        if candidate >= lower:
            yield candidate
        index += 1


def next_occurrence(entry, on_or_after: date) -> date | None:
    return next(occurrences(entry, on_or_after), None)


def count_end_date(entry) -> date | None:
    # Ignore the previous computed end when changing a count schedule.
    from types import SimpleNamespace
    schedule = SimpleNamespace(**{key: getattr(entry, key) for key in (
        "start_date", "repeat_mode", "frequency", "frequency_days", "day_of_month", "month_of_year", "repeat_count",
    )}, end_date=None)
    result = list(islice(occurrences(schedule, schedule.start_date), schedule.repeat_count))
    return result[-1] if len(result) == schedule.repeat_count else None
