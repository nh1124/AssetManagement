from __future__ import annotations

from app.services.money_storage import to_minor


from backend.app.domain.money import Money

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.services.analysis_service import (
    calculate_logical_balance,
    get_summary,
)
from backend.app.services.budget_plan_store import resolve_budget_plan_id
from backend.app.services.fx_service import RateLookup, get_exchange_rate
from backend.app.services.periods import current_period_key


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db) -> models.Client:
    client = models.Client(
        id=1,
        name="Valuation Test",
        general_settings={"currency": "JPY"},
    )
    db.add(client)
    db.commit()
    return client


def _post_opening_cash(db, client_id: int, amount: float) -> models.Account:
    cash = models.Account(client_id=client_id, name="cash", account_type="asset")
    equity = models.Account(client_id=client_id, name="opening", account_type="income")
    db.add_all([cash, equity])
    db.flush()
    transaction = models.Transaction(
        client_id=client_id,
        date=date.today(),
        description="Opening cash",
        amount_minor=Money.from_major(str(amount), "JPY").minor,
        currency="JPY",
    )
    db.add(transaction)
    db.flush()
    db.add_all(
        [
            models.JournalEntry(transaction_id=transaction.id, account_id=cash.id, debit_minor=Money.from_major(str(amount), transaction.currency).minor, credit_minor=Money.from_major(str(0), transaction.currency).minor),
            models.JournalEntry(transaction_id=transaction.id, account_id=equity.id, debit_minor=Money.from_major(str(0), transaction.currency).minor, credit_minor=Money.from_major(str(amount), transaction.currency).minor),
        ]
    )
    db.commit()
    return cash


def test_historical_fx_lookup_does_not_use_future_rate() -> None:
    db = _session()
    try:
        _client(db)
        db.add(
            models.ExchangeRate(
                client_id=1,
                base_currency="USD",
                quote_currency="JPY",
                rate=150,
                as_of_date=date(2026, 7, 1),
                source="manual",
            )
        )
        db.commit()

        assert get_exchange_rate(db, 1, "USD", "JPY", date(2025, 12, 31)) is None
        assert RateLookup(db, 1, "JPY").rate("USD", "JPY", date(2025, 12, 31)) is None
        assert get_exchange_rate(db, 1, "USD", "JPY") == 150
    finally:
        db.close()


def test_summary_budget_deduction_uses_only_default_plan() -> None:
    db = _session()
    try:
        _client(db)
        _post_opening_cash(db, 1, 100000)
        default_plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
        comparison_plan = models.BudgetPlan(client_id=1, name="Comparison", is_default=False)
        db.add_all([default_plan, comparison_plan])
        db.flush()
        period = f"{date.today().year}-{date.today().month:02d}"
        db.add_all(
            [
                models.MonthlyPlanLine(
                    client_id=1,
                    plan_id=default_plan.id,
                    target_period=period,
                    line_type="expense",
                    target_type="manual",
                    name="Baseline expense",
                    amount_minor=to_minor(10000, "JPY"),
                    source="manual",
                    source_kind="manual",
                    identity_key="baseline-expense",
                    is_active=True,
                ),
                models.MonthlyPlanLine(
                    client_id=1,
                    plan_id=comparison_plan.id,
                    target_period=period,
                    line_type="expense",
                    target_type="manual",
                    name="Comparison expense",
                    amount_minor=to_minor(30000, "JPY"),
                    source="manual",
                    source_kind="manual",
                    identity_key="comparison-expense",
                    is_active=True,
                ),
            ]
        )
        db.commit()

        assert get_summary(db, 1)["effective_cash"] == 90000
    finally:
        db.close()


def test_logical_balance_subtracts_the_plan_remainder_not_the_recurring_definition() -> None:
    db = _session()
    try:
        _client(db)
        _post_opening_cash(db, 1, 20000)
        subscription_account = models.Account(client_id=1, name="subscriptions", account_type="expense")
        db.add(subscription_account)
        db.flush()
        due_date = date.today() + timedelta(days=10)
        registry_entry = models.RegistryEntry(client_id=1, name='recurring owner', start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly")
        db.add(registry_entry)
        db.flush()
        db.add_all(
            [
                models.ExchangeRate(
                    client_id=1,
                    base_currency="USD",
                    quote_currency="JPY",
                    rate=150,
                    as_of_date=date.today(),
                    source="manual",
                ),
                models.RegistryEntry(client_id=1, name='USD subscription', amount_minor=to_minor(10, 'USD'), currency='USD', frequency='Monthly', next_due_date=due_date, is_active=True, destination_account_id=subscription_account.id, start_date=date(2026, 1, 1), repeat_mode="indefinite"),
            ]
        )
        db.commit()

        db.add(models.MonthlyPlanLine(
            client_id=1,
            plan_id=resolve_budget_plan_id(db, 1),
            target_period=current_period_key(),
            line_type="expense",
            account_id=subscription_account.id,
            name="Subscription plan",
            amount_minor=to_minor(1500, "JPY"),
            is_active=True,
        ))
        db.commit()

        # The definition is not read; the plan line is.
        assert calculate_logical_balance(db, 1) == 18500
    finally:
        db.close()


