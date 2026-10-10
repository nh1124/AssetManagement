"""A plan line claims the leg on its own account, funded by its own source.

Two lines can watch one expense account -- a subscription paid from a bank and
another paid by card -- and before this rule each claimed the whole account's
movement, so the month counted one payment twice. Narrowing by the line's
source splits them, which leaves the opposite risk: spending that arrives by a
route no line names belongs to nothing, so data_health reports it.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.budget_actuals import actual_for_plan_line
    from backend.app.services.budget_context import BudgetContext
    from backend.app.services.data_health_service import check_data_health
    from backend.app.services.ledger_service import process_transaction
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.budget_actuals import actual_for_plan_line  # type: ignore[no-redef]
    from app.services.budget_context import BudgetContext  # type: ignore[no-redef]
    from app.services.data_health_service import check_data_health  # type: ignore[no-redef]
    from app.services.ledger_service import process_transaction  # type: ignore[no-redef]

PERIOD = "2026-10"
WHEN = date(2026, 10, 5)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _accounts(db):
    db.add(models.Client(id=1, name="test", general_settings={}, ai_config={}))
    bank = models.Account(client_id=1, name="bank", account_type="asset", balance=500000)
    card = models.Account(
        client_id=1, name="card", account_type="liability", liability_kind="card", balance=0
    )
    subs = models.Account(client_id=1, name="subscriptions", account_type="expense", balance=0)
    db.add_all([bank, card, subs])
    db.flush()
    return bank, card, subs


def _plan_line(db, **kwargs):
    line = models.MonthlyPlanLine(
        client_id=1,
        target_period=PERIOD,
        line_type="expense",
        target_type="account",
        amount=0.0,
        **kwargs,
    )
    db.add(line)
    db.flush()
    return line


def _post(db, description, amount, credit, debit, when=WHEN):
    tx = models.Transaction(
        client_id=1, date=when, description=description, amount=amount, currency="JPY"
    )
    db.add(tx)
    db.flush()
    process_transaction(db, tx, from_account_id=credit.id, to_account_id=debit.id)
    return tx


def test_two_lines_on_one_account_each_take_their_own_funding() -> None:
    db = _session()
    try:
        bank, card, subs = _accounts(db)
        from_bank = _plan_line(db, name="subscriptions", account_id=subs.id, source_account_id=bank.id)
        from_card = _plan_line(db, name="subscriptions (card)", account_id=subs.id, source_account_id=card.id)
        _post(db, "ChatGPT", 3000, bank, subs)
        _post(db, "sakura VPS", 2000, card, subs)
        db.commit()

        ctx = BudgetContext(db, 1)
        bank_actual = actual_for_plan_line(ctx, from_bank, PERIOD)
        card_actual = actual_for_plan_line(ctx, from_card, PERIOD)

        assert (bank_actual, card_actual) == (3000, 2000)
        # The account moved 5,000 once, and the two lines report it once.
        assert bank_actual + card_actual == 5000
    finally:
        db.close()


def test_a_line_without_a_source_still_takes_everything_on_its_account() -> None:
    db = _session()
    try:
        bank, card, subs = _accounts(db)
        line = _plan_line(db, name="subscriptions", account_id=subs.id)
        _post(db, "ChatGPT", 3000, bank, subs)
        _post(db, "sakura VPS", 2000, card, subs)
        db.commit()

        ctx = BudgetContext(db, 1)

        assert actual_for_plan_line(ctx, line, PERIOD) == 5000
    finally:
        db.close()


def test_spending_from_a_route_no_line_names_is_reported_not_absorbed() -> None:
    db = _session()
    try:
        bank, card, subs = _accounts(db)
        line = _plan_line(db, name="subscriptions", account_id=subs.id, source_account_id=bank.id)
        _post(db, "ChatGPT", 3000, bank, subs)
        cash_paid = _post(db, "a subscription bought on the card", 2000, card, subs)
        db.commit()

        ctx = BudgetContext(db, 1)
        assert actual_for_plan_line(ctx, line, PERIOD) == 3000

        issues = {issue["code"]: issue for issue in check_data_health(db, 1)["issues"]}
        unclaimed = issues["budget_leg_unclaimed"]

        assert unclaimed["count"] == 1
        item = unclaimed["items"][0]
        assert item["transaction_id"] == cash_paid.id
        assert item["account_id"] == subs.id
        assert item["amount"] == 2000
        assert item["line_sources"] == [bank.id]
        # Only a person can say whether the line's source is wrong or a second
        # line is missing.
        assert item["repairable"] is False
        assert unclaimed["repairable"] is False
    finally:
        db.close()


def test_nothing_is_reported_when_every_leg_belongs_to_a_line() -> None:
    db = _session()
    try:
        bank, card, subs = _accounts(db)
        _plan_line(db, name="subscriptions", account_id=subs.id, source_account_id=bank.id)
        _plan_line(db, name="subscriptions (card)", account_id=subs.id, source_account_id=card.id)
        _post(db, "ChatGPT", 3000, bank, subs)
        _post(db, "sakura VPS", 2000, card, subs)
        db.commit()

        issues = {issue["code"]: issue for issue in check_data_health(db, 1)["issues"]}

        assert issues["budget_leg_unclaimed"]["count"] == 0
    finally:
        db.close()
