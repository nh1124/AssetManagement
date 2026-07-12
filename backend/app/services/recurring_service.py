from __future__ import annotations

import calendar
from datetime import date

from sqlalchemy.orm import Session

from .. import models
from .cache_service import invalidate_client


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


def post_recurring_transaction(
    db: Session,
    recurring: models.RecurringTransaction,
    posting_date: date,
) -> models.Transaction:
    """Create a transaction and its journal entries without committing."""
    to_account = None
    if recurring.to_account_id:
        to_account = db.query(models.Account).filter(
            models.Account.id == recurring.to_account_id,
            models.Account.client_id == recurring.client_id,
        ).first()
    category = to_account.name if to_account else recurring.name
    transaction = models.Transaction(
        client_id=recurring.client_id,
        date=posting_date,
        description=recurring.name,
        amount=recurring.amount,
        currency=recurring.currency,
        type=recurring.type,
        from_account_id=recurring.from_account_id,
        to_account_id=recurring.to_account_id,
        category=category,
    )
    db.add(transaction)
    db.flush()
    from .accounting_service import post_transaction_journal
    from .capsule_service import apply_capsule_rules_for_transaction

    post_transaction_journal(db, transaction)
    apply_capsule_rules_for_transaction(db, transaction, commit=False)
    return transaction


def process_due_for_client(db: Session, client_id: int, today: date | None = None) -> dict:
    """Post due auto-post definitions, catching up at most 24 periods each."""
    effective_today = today or date.today()
    recurring_rows = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == client_id,
        models.RecurringTransaction.is_active.is_(True),
        models.RecurringTransaction.auto_post.is_(True),
        models.RecurringTransaction.next_due_date.isnot(None),
        models.RecurringTransaction.next_due_date <= effective_today,
    ).with_for_update(skip_locked=True).all()

    processed: list[dict] = []
    deactivated: list[int] = []
    try:
        for recurring in recurring_rows:
            transaction_ids: list[int] = []
            periods = 0
            while (
                recurring.is_active
                and recurring.next_due_date is not None
                and recurring.next_due_date <= effective_today
                and periods < 24
            ):
                due = recurring.next_due_date
                if is_past_end_period(recurring, due):
                    recurring.is_active = False
                    from .registry_service import sync_registry_from_recurring

                    sync_registry_from_recurring(db, recurring)
                    deactivated.append(recurring.id)
                    break

                transaction = post_recurring_transaction(db, recurring, due)
                transaction_ids.append(transaction.id)
                advance_next_due_date(recurring)
                periods += 1

                if recurring.next_due_date and is_past_end_period(recurring, recurring.next_due_date):
                    recurring.is_active = False
                    from .registry_service import sync_registry_from_recurring

                    sync_registry_from_recurring(db, recurring)
                    deactivated.append(recurring.id)
                    break
            if transaction_ids:
                processed.append(
                    {
                        "recurring_id": recurring.id,
                        "transaction_ids": transaction_ids,
                        "next_due_date": recurring.next_due_date,
                    }
                )

        db.commit()
    except Exception:
        db.rollback()
        raise

    if processed or deactivated:
        invalidate_client(client_id)
    return {"processed": processed, "deactivated": deactivated}
