"""Card settlements add posted activity and the plan's remaining expectation."""

from __future__ import annotations

from datetime import date

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services import budget_actuals
    from backend.app.services.budget_context import BudgetContext
    from backend.app.services.budget_credit_settlement import credit_settlement_plan_lines
    from backend.app.services.ledger_service import process_transaction
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services import budget_actuals  # type: ignore[no-redef]
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


def _plan(db, card, subs, amount=5000, plan_id=None):
    row = models.MonthlyPlanLine(
        client_id=1, plan_id=plan_id, target_period="2026-10", line_type="expense",
        target_type="account", account_id=subs.id, source_account_id=card.id,
        name="subscriptions", amount=amount, is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _post(db, card, subs, amount):
    tx = models.Transaction(client_id=1, date=date(2026, 10, 11), description="subscription", amount=amount, currency="JPY")
    db.add(tx)
    db.flush()
    process_transaction(db, tx, from_account_id=card.id, to_account_id=subs.id)


@pytest.fixture
def card_plan(monkeypatch):
    monkeypatch.setattr(budget_actuals, "current_period_key", lambda: "2026-10")
    db = _session()
    card, subs = _card_and_subscription(db)
    try:
        yield db, card, subs
    finally:
        db.close()


def test_a_posted_occurrence_is_counted_once(card_plan):
    db, card, subs = card_plan
    db.add(models.RecurringTransaction(
        client_id=1, name="subscription", amount=3000, currency="JPY",
        from_account_id=card.id, to_account_id=subs.id, frequency="Monthly",
        day_of_month=11, next_due_date=date(2026, 10, 11), is_active=True,
    ))
    _post(db, card, subs, 3000)
    db.commit()
    assert credit_settlement_plan_lines(BudgetContext(db, 1), "2026-11")[0]["suggested_amount"] == 3000


def test_an_unspent_plan_line_is_added_to_settlement(card_plan):
    db, card, subs = card_plan
    _plan(db, card, subs, 3000)
    db.commit()
    assert credit_settlement_plan_lines(BudgetContext(db, 1), "2026-11")[0]["suggested_amount"] == 3000


def test_a_fully_spent_plan_line_is_counted_once(card_plan):
    db, card, subs = card_plan
    _plan(db, card, subs, 3000)
    _post(db, card, subs, 3000)
    db.commit()
    line = credit_settlement_plan_lines(BudgetContext(db, 1), "2026-11")[0]
    assert line["suggested_amount"] == 3000
    assert line["suggested_items"][0]["planned_remaining"] == 0
