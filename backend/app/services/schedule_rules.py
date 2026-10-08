"""Pure scheduling rules for recurring transactions.

Leaf module (layer 0): depends only on the ORM models, never on a Session or
another service. Lives apart from `recurring_service` so that `registry_service`
can reuse the due-date arithmetic without importing its own downstream consumer.
"""
from __future__ import annotations

import calendar
from datetime import date

from .. import models


def _month_due(year: int, month: int, day_of_month: int | None) -> date:
    day = max(1, min(day_of_month or 1, calendar.monthrange(year, month)[1]))
    return date(year, month, day)


def _parse_period(period: str | None) -> tuple[int, int] | None:
    if not period:
        return None
    try:
        year_text, month_text = period.split("-", 1)
        year, month = int(year_text), int(month_text)
        if 1 <= month <= 12:
            return year, month
    except (TypeError, ValueError):
        pass
    return None


def compute_next_due_date(recurring: models.RecurringTransaction, today: date) -> date:
    """Return the first scheduled due date on or after today and start_period."""
    start = _parse_period(recurring.start_period)
    minimum_month = (today.year, today.month)
    if start and start > minimum_month:
        minimum_month = start

    if recurring.frequency == "Yearly":
        month = recurring.month_of_year or (start[1] if start else today.month)
        year = minimum_month[0]
        candidate = _month_due(year, month, recurring.day_of_month)
        minimum_date = max(today, date(minimum_month[0], minimum_month[1], 1))
        if candidate < minimum_date:
            candidate = _month_due(year + 1, month, recurring.day_of_month)
        return candidate

    year, month = minimum_month
    candidate = _month_due(year, month, recurring.day_of_month)
    if candidate < today:
        month += 1
        if month > 12:
            year, month = year + 1, 1
        candidate = _month_due(year, month, recurring.day_of_month)
    return candidate


def ensure_next_due_date(recurring: models.RecurringTransaction, today: date) -> None:
    """Initialize next_due_date without overwriting an existing progression state."""
    if recurring.next_due_date is None:
        recurring.next_due_date = compute_next_due_date(recurring, today)


def advance_next_due_date(recurring: models.RecurringTransaction) -> None:
    """Advance one period while restoring the configured day after month-end clamping."""
    if recurring.next_due_date is None:
        ensure_next_due_date(recurring, date.today())
    current = recurring.next_due_date
    if current is None:
        return

    if recurring.frequency == "Yearly":
        recurring.next_due_date = _month_due(
            current.year + 1,
            recurring.month_of_year or current.month,
            recurring.day_of_month,
        )
        return

    year, month = current.year, current.month + 1
    if month > 12:
        year, month = year + 1, 1
    recurring.next_due_date = _month_due(year, month, recurring.day_of_month)


def is_past_end_period(recurring: models.RecurringTransaction, due: date) -> bool:
    end = _parse_period(recurring.end_period)
    return bool(end and (due.year, due.month) > end)
