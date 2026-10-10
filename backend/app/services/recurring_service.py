from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models
from .cache_service import invalidate_client
from .ledger_service import create_transaction
from .capsule_service import apply_capsule_rules_for_transaction
from .schedule_rules import (
    _month_due,
    _parse_period,
    advance_next_due_date,
    compute_next_due_date,
    ensure_next_due_date,
    is_past_end_period,
)


def post_recurring_transaction(
    db: Session,
    recurring: models.RecurringTransaction,
    posting_date: date,
) -> models.Transaction:
    """Create a transaction and its journal entries without committing."""
    transaction = create_transaction(
        db,
        client_id=recurring.client_id,
        recurring_transaction_id=recurring.id,
        date=posting_date,
        description=recurring.name,
        amount=recurring.amount,
        currency=recurring.currency,
        from_account_id=recurring.from_account_id,
        to_account_id=recurring.to_account_id,
    )
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

                    deactivated.append(recurring.id)
                    break

                transaction = post_recurring_transaction(db, recurring, due)
                transaction_ids.append(transaction.id)
                advance_next_due_date(recurring)
                periods += 1

                if recurring.next_due_date and is_past_end_period(recurring, recurring.next_due_date):
                    recurring.is_active = False

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
