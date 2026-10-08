"""Liability payment scheduling rules.

Leaf module: works out which period a card charge settles in and how much of
the balance is actually paid, from the schedule columns on the account. Pure
functions over the ORM objects -- no Session, no query.
"""
from __future__ import annotations

from datetime import date

from .. import models
from .periods import _last_day_of_month, add_months, period_to_range


def _account_has_liability_schedule(account: models.Account) -> bool:
    return bool(
        account.liability_closing_day
        or account.liability_payment_day
        or (account.liability_payment_month_offset or 0) > 0
    )


def _statement_period_for_liability(account: models.Account, activity_date: date) -> str:
    period = f"{activity_date.year}-{activity_date.month:02d}"
    closing_day = account.liability_closing_day
    if closing_day and activity_date.day > closing_day:
        period = add_months(period, 1)
    return period


def _settlement_period_for_liability(account: models.Account, activity_date: date) -> str:
    offset = max(0, int(account.liability_payment_month_offset or 0))
    return add_months(_statement_period_for_liability(account, activity_date), offset)


def _liability_activity_allocations(account: models.Account, activity_date: date, amount: float) -> list[tuple[str, float]]:
    amount = max(0.0, amount or 0.0)
    if amount <= 0:
        return []
    first_period = _settlement_period_for_liability(account, activity_date)
    if (account.liability_payment_policy or "full") == "installment":
        months = max(1, int(account.liability_installment_months or 1))
        installment_amount = amount / months
        return [(add_months(first_period, index), installment_amount) for index in range(months)]
    return [(first_period, amount)]


def _recurring_activity_date(row: models.RecurringTransaction, period: str) -> date:
    start, _ = period_to_range(period)
    day = min(max(1, row.day_of_month or 1), _last_day_of_month(period))
    return date(start.year, start.month, day)


def _recurring_applies_to_period(row: models.RecurringTransaction, period: str) -> bool:
    if row.start_period and row.start_period > period:
        return False
    if row.end_period and row.end_period < period:
        return False
    if row.frequency == "Yearly":
        month = int(period.split("-")[1])
        return not row.month_of_year or row.month_of_year == month
    return True


def _apply_liability_payment_policy(account: models.Account, amount: float) -> float:
    amount = max(0.0, amount or 0.0)
    if amount <= 0:
        return 0.0
    policy = account.liability_payment_policy or "full"
    minimum = max(0.0, account.liability_minimum_payment or 0.0)
    if policy == "minimum":
        return min(amount, minimum or amount)
    if policy == "fixed":
        fixed = max(0.0, account.liability_fixed_payment_amount or 0.0)
        return min(amount, fixed or amount)
    if policy == "installment":
        return amount
    if policy == "revolving":
        rate_amount = amount * max(0.0, account.liability_revolving_rate or 0.0) / 100
        payment = max(minimum, rate_amount)
        return min(amount, payment or amount)
    return amount
