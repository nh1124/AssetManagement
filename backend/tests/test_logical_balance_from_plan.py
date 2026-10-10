from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.services.analysis_service import calculate_logical_balance
from backend.app.services.budget_context import BudgetContext
from backend.app.services.budget_plan_store import resolve_budget_plan_id
from backend.app.services.periods import add_months, current_period_key


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db) -> models.Client:
    client = models.Client(
        id=1,
        name="Valuation Test",
        general_settings={"currency": "JPY"},
        ai_config={},
    )
    db.add(client)
    db.commit()
    return client


def _post_opening_cash(db, client_id: int, amount: float) -> models.Account:
    cash = models.Account(
        client_id=client_id,
        name="cash",
        account_type="asset",
        balance=amount,
    )
    equity = models.Account(
        client_id=client_id,
        name="opening",
        account_type="income",
        balance=amount,
    )
    db.add_all([cash, equity])
    db.flush()
    transaction = models.Transaction(
        client_id=client_id,
        date=date.today(),
        description="Opening cash",
        amount=amount,
        currency="JPY",
    )
    db.add(transaction)
    db.flush()
    db.add_all(
        [
            models.JournalEntry(
                transaction_id=transaction.id,
                account_id=cash.id,
                debit=amount,
                credit=0,
            ),
            models.JournalEntry(
                transaction_id=transaction.id,
                account_id=equity.id,
                debit=0,
                credit=amount,
            ),
        ]
    )
    db.commit()
    return cash


def _plan_line(db, amount, *, line_type="expense", period=None, plan_id=None, **kwargs):
    line = models.MonthlyPlanLine(
        client_id=1,
        plan_id=resolve_budget_plan_id(db, 1, plan_id),
        target_period=period or current_period_key(),
        line_type=line_type,
        name="Planned " + line_type,
        amount=amount,
        is_active=True,
        **kwargs,
    )
    db.add(line)
    db.commit()
    return line


def test_card_funded_expense_reserves_non_cash_budget() -> None:
    db = _session()
    try:
        _client(db)
        _post_opening_cash(db, 1, 20000)
        card = models.Account(
            client_id=1,
            name="card",
            account_type="liability",
            liability_kind="card",
        )
        expense = models.Account(
            client_id=1,
            name="spending",
            account_type="expense",
        )
        db.add_all([card, expense])
        db.flush()
        _plan_line(
            db,
            5000,
            account_id=expense.id,
            source_account_id=card.id,
            cash_treatment="auto",
        )

        assert calculate_logical_balance(db, 1) == 15000
    finally:
        db.close()


def test_posted_expense_leaves_only_plan_remainder() -> None:
    db = _session()
    try:
        _client(db)
        cash = _post_opening_cash(db, 1, 20000)
        expense = models.Account(
            client_id=1,
            name="spending",
            account_type="expense",
        )
        db.add(expense)
        db.flush()
        _plan_line(
            db,
            5000,
            account_id=expense.id,
            source_account_id=cash.id,
        )
        transaction = models.Transaction(
            client_id=1,
            date=date.today(),
            description="Posted spending",
            amount=3000,
            currency="JPY",
        )
        db.add(transaction)
        db.flush()
        db.add_all(
            [
                models.JournalEntry(
                    transaction_id=transaction.id,
                    account_id=expense.id,
                    debit=3000,
                    credit=0,
                ),
                models.JournalEntry(
                    transaction_id=transaction.id,
                    account_id=cash.id,
                    debit=0,
                    credit=3000,
                ),
            ]
        )
        db.commit()

        # Cash is now 17,000; only the unposted 2,000 is still reserved.
        assert calculate_logical_balance(db, 1) == 15000
        assert calculate_logical_balance(db, 1, ctx=BudgetContext(db, 1)) == 15000
    finally:
        db.close()


def test_debt_payment_does_not_subtract_liability_twice() -> None:
    db = _session()
    try:
        _client(db)
        cash = _post_opening_cash(db, 1, 20000)
        card = models.Account(
            client_id=1,
            name="card",
            account_type="liability",
        )
        db.add(card)
        db.flush()
        opening = db.query(models.Account).filter(models.Account.name == "opening").one()
        transaction = models.Transaction(
            client_id=1,
            date=date.today(),
            description="Opening liability",
            amount=10000,
            currency="JPY",
        )
        db.add(transaction)
        db.flush()
        db.add_all(
            [
                models.JournalEntry(
                    transaction_id=transaction.id,
                    account_id=opening.id,
                    debit=10000,
                    credit=0,
                ),
                models.JournalEntry(
                    transaction_id=transaction.id,
                    account_id=card.id,
                    debit=0,
                    credit=10000,
                ),
            ]
        )
        _plan_line(
            db,
            10000,
            line_type="debt_payment",
            account_id=card.id,
            source_account_id=cash.id,
        )

        assert calculate_logical_balance(db, 1) == 10000
    finally:
        db.close()


def test_capsule_allocation_does_not_reserve_unfunded_plan() -> None:
    db = _session()
    try:
        _client(db)
        cash = _post_opening_cash(db, 1, 20000)
        capsule = models.Capsule(
            client_id=1,
            name="Reserve",
            current_balance=1000,
        )
        db.add(capsule)
        db.commit()
        assert calculate_logical_balance(db, 1) == 19000
        _plan_line(
            db,
            4000,
            line_type="allocation",
            target_type="capsule",
            target_id=capsule.id,
            source_account_id=cash.id,
        )

        assert calculate_logical_balance(db, 1) == 19000
    finally:
        db.close()


def test_planned_income_does_not_raise_logical_balance() -> None:
    db = _session()
    try:
        _client(db)
        _post_opening_cash(db, 1, 20000)
        _plan_line(
            db,
            50000,
            line_type="income",
        )

        assert calculate_logical_balance(db, 1) == 20000
    finally:
        db.close()


def test_next_month_plan_does_not_affect_logical_balance() -> None:
    db = _session()
    try:
        _client(db)
        _post_opening_cash(db, 1, 20000)
        _plan_line(
            db,
            5000,
            period=add_months(current_period_key(), 1),
        )

        assert calculate_logical_balance(db, 1) == 20000
    finally:
        db.close()


def test_only_default_budget_plan_reduces_logical_balance() -> None:
    db = _session()
    try:
        _client(db)
        _post_opening_cash(db, 1, 20000)
        default = models.BudgetPlan(
            client_id=1,
            name="Baseline",
            is_default=True,
        )
        comparison = models.BudgetPlan(
            client_id=1,
            name="Comparison",
            is_default=False,
        )
        db.add_all([default, comparison])
        db.commit()
        _plan_line(
            db,
            5000,
            plan_id=default.id,
        )
        _plan_line(
            db,
            12000,
            plan_id=comparison.id,
        )

        assert calculate_logical_balance(db, 1) == 15000
    finally:
        db.close()
