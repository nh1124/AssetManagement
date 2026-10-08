"""Period arithmetic for budget planning.

Leaf module (layer 0): a period is the string "YYYY-MM" used throughout the
planning code. Pure functions, no Session, no other service.
"""
from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta


def period_to_range(period: str) -> tuple[date, date]:
    year, month = [int(part) for part in period.split("-")]
    start = date(year, month, 1)
    end = start + relativedelta(months=1)
    return start, end


def add_months(period: str, months: int) -> str:
    start, _ = period_to_range(period)
    shifted = start + relativedelta(months=months)
    return f"{shifted.year}-{shifted.month:02d}"


def period_months_between(start_period: str, end_period: str) -> list[str]:
    start, _ = period_to_range(start_period)
    end, _ = period_to_range(end_period)
    periods = []
    cursor = start
    while cursor <= end:
        periods.append(f"{cursor.year}-{cursor.month:02d}")
        cursor += relativedelta(months=1)
    return periods


def current_period_key(today: date | None = None) -> str:
    today = today or date.today()
    return f"{today.year}-{today.month:02d}"


def _last_day_of_month(period: str) -> int:
    start, _ = period_to_range(period)
    return (start + relativedelta(day=31)).day
