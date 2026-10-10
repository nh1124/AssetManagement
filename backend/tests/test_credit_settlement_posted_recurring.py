"""A card charge the recurring rule already posted is not projected again.

The settlement projection adds the card activity posted in the statement month
to the card-funded recurring definitions that fall in it. For a month already
posted that is the same subscription twice. It stayed hidden while the card had
no statement schedule, because the projection then took the whole balance and
ignored the activity total.

next_due_date is how far posting has got: occurrences before it are on the
ledger already.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.budget_context import BudgetContext
    from backend.app.services.budget_credit_settlement import credit_settlement_plan_lines
    from backend.app.services.ledger_service import process_transaction
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.budget_context import BudgetContext  # type: ignore[no-redef]
    from app.services.budget_credit_settlement import credit_settlement_plan_lines  # type: ignore[no-redef]
    from app.services.ledger_service import process_transaction  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _card_and_subscription(db):
    db.add(models.Client(id=1, name="test", general_settings={}, ai_config={}))
    card = models.Account(
        client_id=1,
        name="card",
        account_type="liability",
        liability_kind="card",
        liability_closing_day=31,
        liability_payment_day=27,
        liability_payment_month_offset=1,
        liability_payment_policy="full",
        balance=0,
    )
    subs = models.Account(client_id=1, name="subscriptions", account_type="expense", balance=0)
    db.add_all([card, subs])
    db.flush()
    return card, subs


def _recurring(db, card, subs, *, next_due: date) -> models.RecurringTransaction:
    row = models.RecurringTransaction(
        client_id=1,
        name="a monthly subscription",
        amount=3000,
        currency="JPY",
        from_account_id=card.id,
        to_account_id=subs.id,
        frequency="Monthly",
        day_of_month=11,
        next_due_date=next_due,
        auto_post=True,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _settlement(db, period: str) -> float:
    ctx = BudgetContext(db, 1)
    lines = [
        line for line in credit_settlement_plan_lines(ctx, period)
        if line.get("source_kind") == "credit_settlement"
    ]
    return sum(line.get("suggested_amount") or 0.0 for line in lines)


def test_a_posted_occurrence_is_counted_once() -> None:
    db = _session()
    try:
        card, subs = _card_and_subscription(db)
        # October is posted; the rule has moved on to November.
        _recurring(db, card, subs, next_due=date(2026, 11, 11))
        tx = models.Transaction(
            client_id=1, date=date(2026, 10, 11), description="a monthly subscription",
            amount=3000, currency="JPY",
        )
        db.add(tx)
        db.flush()
        process_transaction(db, tx, from_account_id=card.id, to_account_id=subs.id)
        db.commit()

        # The October statement is paid in November: the charge, once.
        assert _settlement(db, "2026-11") == 3000
    finally:
        db.close()


def test_an_occurrence_still_to_come_is_projected() -> None:
    db = _session()
    try:
        card, subs = _card_and_subscription(db)
        _recurring(db, card, subs, next_due=date(2026, 10, 11))
        db.commit()

        # Nothing posted yet, so October's statement is the projection alone.
        assert _settlement(db, "2026-11") == 3000
    finally:
        db.close()


def test_a_posted_rule_and_a_pending_one_are_each_counted_once() -> None:
    db = _session()
    try:
        card, subs = _card_and_subscription(db)
        # Two card-funded subscriptions in the same statement month: one the
        # auto-post has already written and moved past, one still to come.
        _recurring(db, card, subs, next_due=date(2026, 11, 11))
        pending = _recurring(db, card, subs, next_due=date(2026, 10, 20))
        pending.amount = 5000
        pending.day_of_month = 20
        db.flush()
        tx = models.Transaction(
            client_id=1, date=date(2026, 10, 11), description="a monthly subscription",
            amount=3000, currency="JPY",
        )
        db.add(tx)
        db.flush()
        process_transaction(db, tx, from_account_id=card.id, to_account_id=subs.id)
        db.commit()

        # The posted 3,000 off the ledger and the pending 5,000 from the
        # definition, each exactly once.
        assert _settlement(db, "2026-11") == 8000
    finally:
        db.close()
