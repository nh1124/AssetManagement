"""A transaction with more than two legs (P7-001).

The case these tests describe is a meal paid by card where part of the bill was
fronted for someone else: one credit leg on the card, two debit legs -- the
expense and a receivable. Nothing in the existing data looks like this yet, so
these are the executable statement of the rule rather than a regression guard.

The rule: a plan line claims the leg on its own account, on the side bookkeeping
puts it. An expense line takes the expense leg and nothing else; the receivable
leg belongs to no plan line at all.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.budget_actuals import (
        actual_for_plan_line,
        cash_flow_actual_for_plan_line,
        plan_line_has_cash_impact,
    )
    from backend.app.services.budget_context import BudgetContext
    from backend.app.services.budget_credit_settlement import credit_settlement_plan_lines
    from backend.app.services.reporting_service import get_profit_loss_for_range
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.budget_actuals import (  # type: ignore[no-redef]
        actual_for_plan_line,
        cash_flow_actual_for_plan_line,
        plan_line_has_cash_impact,
    )
    from app.services.budget_context import BudgetContext  # type: ignore[no-redef]
    from app.services.budget_credit_settlement import credit_settlement_plan_lines  # type: ignore[no-redef]
    from app.services.reporting_service import get_profit_loss_for_range  # type: ignore[no-redef]

PERIOD = "2026-10"
WHEN = date(2026, 10, 5)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _split_meal(db):
    """5,000 on the card: 3,000 our own food, 2,000 fronted for a friend."""
    client = models.Client(id=1, name="test", general_settings={}, ai_config={})
    card = models.Account(
        client_id=1, name="card", account_type="liability", liability_kind="card", balance=0
    )
    food = models.Account(client_id=1, name="food", account_type="expense", balance=0)
    advance = models.Account(
        client_id=1, name="advance / friend", account_type="asset", role="unassigned", balance=0
    )
    db.add_all([client, card, food, advance])
    db.flush()

    tx = models.Transaction(
        client_id=1,
        date=WHEN,
        description="dinner with a friend",
        amount=5000,
        type="CreditExpense",
        currency="JPY",
        from_account_id=card.id,
    )
    db.add(tx)
    db.flush()
    db.add_all([
        models.JournalEntry(transaction_id=tx.id, account_id=card.id, debit=0, credit=5000, sort_order=0),
        models.JournalEntry(
            transaction_id=tx.id, account_id=food.id, debit=3000, credit=0, memo="own share", sort_order=1
        ),
        models.JournalEntry(
            transaction_id=tx.id,
            account_id=advance.id,
            debit=2000,
            credit=0,
            memo="advance / friend",
            sort_order=2,
        ),
    ])
    # The cached balances follow the legs, as the posting code does per leg.
    card.balance = 5000
    food.balance = 3000
    advance.balance = 2000
    db.commit()
    return client, card, food, advance, tx


def _plan_line(db, *, line_type, account_id, source_account_id, name, amount):
    line = models.MonthlyPlanLine(
        client_id=1,
        target_period=PERIOD,
        line_type=line_type,
        target_type="account",
        account_id=account_id,
        source_account_id=source_account_id,
        name=name,
        amount=amount,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def test_expense_plan_line_takes_only_its_own_leg() -> None:
    db = _session()
    try:
        _client, card, food, _advance, _tx = _split_meal(db)
        line = _plan_line(
            db, line_type="expense", account_id=food.id, source_account_id=card.id,
            name="food", amount=4000,
        )
        ctx = BudgetContext(db, 1)

        # 3,000, not the 5,000 the card was charged and not the 2,000 fronted.
        assert actual_for_plan_line(ctx, line, PERIOD) == 3000
    finally:
        db.close()


def test_no_plan_line_claims_the_whole_bill() -> None:
    """The point of matching per leg: the 5,000 is not counted twice.

    Matching at transaction level, both plan lines would have seen the whole
    bill and the month's actuals would have come to 10,000 against a 5,000
    payment. Each line sees its own leg, and together they account for the
    payment exactly once.
    """
    db = _session()
    try:
        _client, card, food, advance, _tx = _split_meal(db)
        expense_line = _plan_line(
            db, line_type="expense", account_id=food.id, source_account_id=card.id,
            name="food", amount=4000,
        )
        advance_line = _plan_line(
            db, line_type="allocation", account_id=advance.id, source_account_id=card.id,
            name="advance / friend", amount=2000,
        )
        ctx = BudgetContext(db, 1)

        claimed = [
            actual_for_plan_line(ctx, expense_line, PERIOD),
            actual_for_plan_line(ctx, advance_line, PERIOD),
        ]

        assert claimed == [3000, 2000]
        assert sum(claimed) == 5000
    finally:
        db.close()


def test_allocation_plan_line_takes_the_receivable_leg() -> None:
    db = _session()
    try:
        _client, card, _food, advance, _tx = _split_meal(db)
        line = _plan_line(
            db, line_type="allocation", account_id=advance.id, source_account_id=card.id,
            name="advance / friend", amount=2000,
        )
        ctx = BudgetContext(db, 1)

        assert actual_for_plan_line(ctx, line, PERIOD) == 2000
    finally:
        db.close()


def test_profit_loss_counts_only_the_expense_leg() -> None:
    db = _session()
    try:
        _split_meal(db)

        pl = get_profit_loss_for_range(db, date(2026, 10, 1), date(2026, 10, 31), 1)

        assert pl["expenses"] == [{"category": "food", "amount": 3000}]
        assert pl["total_expenses"] == 3000
    finally:
        db.close()


def test_the_card_is_charged_the_whole_bill() -> None:
    db = _session()
    try:
        _split_meal(db)
        ctx = BudgetContext(db, 1)

        lines = credit_settlement_plan_lines(ctx, PERIOD)

        assert len(lines) == 1
        assert lines[0]["account_name"] == "card"
        # The split is ours to account for; the card issuer wants all 5,000.
        assert lines[0]["suggested_amount"] == 5000
    finally:
        db.close()


def test_a_card_funded_line_moves_no_cash_this_month() -> None:
    db = _session()
    try:
        _client, card, food, _advance, _tx = _split_meal(db)
        line = _plan_line(
            db, line_type="expense", account_id=food.id, source_account_id=card.id,
            name="food", amount=4000,
        )
        ctx = BudgetContext(db, 1)

        assert plan_line_has_cash_impact(ctx, line) is False
        assert cash_flow_actual_for_plan_line(ctx, line, PERIOD) == 0
    finally:
        db.close()


def test_a_cash_funded_line_still_reports_its_own_leg_as_cash() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", role="operating", balance=0)
        food = models.Account(client_id=1, name="food", account_type="expense", balance=0)
        advance = models.Account(client_id=1, name="advance", account_type="asset", balance=0)
        db.add_all([client, cash, food, advance])
        db.flush()
        tx = models.Transaction(
            client_id=1, date=WHEN, description="dinner", amount=5000,
            type="Expense", currency="JPY", from_account_id=cash.id,
        )
        db.add(tx)
        db.flush()
        db.add_all([
            models.JournalEntry(transaction_id=tx.id, account_id=cash.id, debit=0, credit=5000),
            models.JournalEntry(transaction_id=tx.id, account_id=food.id, debit=3000, credit=0),
            models.JournalEntry(transaction_id=tx.id, account_id=advance.id, debit=2000, credit=0),
        ])
        cash.balance = -5000
        food.balance = 3000
        advance.balance = 2000
        db.commit()

        line = _plan_line(
            db, line_type="expense", account_id=food.id, source_account_id=cash.id,
            name="food", amount=4000,
        )
        ctx = BudgetContext(db, 1)

        assert plan_line_has_cash_impact(ctx, line) is True
        assert cash_flow_actual_for_plan_line(ctx, line, PERIOD) == 3000
    finally:
        db.close()
