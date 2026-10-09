"""The advance pairs data_health reports, and refuses to touch (P7-001 W5).

Fronting money for someone used to need two transactions, because one payment
could only reach one account. The pair is arithmetically fine; what it gets
wrong is the month in between, where the fronted share sits in the expenses as
if it had been spent.

These tests pin down what counts as a pair, and that it is only ever reported.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.data_health_service import check_data_health
    from backend.app.services.ledger_service import process_transaction
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.data_health_service import check_data_health  # type: ignore[no-redef]
    from app.services.ledger_service import process_transaction  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _accounts(db):
    db.add(models.Client(id=1, name="test", general_settings={}, ai_config={}))
    cash = models.Account(client_id=1, name="cash", account_type="asset", balance=100000)
    food = models.Account(client_id=1, name="food", account_type="expense", balance=0)
    db.add_all([cash, food])
    db.flush()
    return cash, food


def _post(db, description: str, amount: float, when: date, credit, debit):
    tx = models.Transaction(
        client_id=1, date=when, description=description, amount=amount, currency="JPY"
    )
    db.add(tx)
    db.flush()
    process_transaction(db, tx, from_account_id=credit.id, to_account_id=debit.id)
    return tx


def _advance_issue(db):
    issues = {issue["code"]: issue for issue in check_data_health(db, 1)["issues"]}
    return issues["advance_pair_candidate"]


def test_a_bill_and_its_settlement_are_reported_as_one_pair() -> None:
    db = _session()
    try:
        cash, food = _accounts(db)
        bill = _post(db, "dinner, note: advance for a friend", 5000, date(2026, 5, 4), cash, food)
        back = _post(db, "note: dinner advance, reimburse", 5000, date(2026, 5, 20), food, cash)
        db.commit()

        issue = _advance_issue(db)

        assert issue["count"] == 1
        item = issue["items"][0]
        assert item["transaction_id"] == bill.id
        assert item["settlement_transaction_id"] == back.id
        assert item["amount"] == 5000
        assert item["funding_account_id"] == cash.id
        # History is not rewritten for the user: the split needs to know whose
        # share was whose, which the two rows never recorded.
        assert item["repairable"] is False
        assert issue["repairable"] is False
    finally:
        db.close()


def test_the_settlement_half_is_not_also_reported_as_a_bill() -> None:
    db = _session()
    try:
        cash, food = _accounts(db)
        _post(db, "dinner, note: advance", 5000, date(2026, 5, 4), cash, food)
        _post(db, "note: dinner advance, reimburse", 5000, date(2026, 5, 20), food, cash)
        db.commit()

        items = _advance_issue(db)["items"]

        assert len(items) == 1
        assert items[0]["settlement_transaction_id"] not in {item["transaction_id"] for item in items}
    finally:
        db.close()


def test_one_settlement_is_claimed_by_one_bill() -> None:
    db = _session()
    try:
        cash, food = _accounts(db)
        first = _post(db, "dinner 1, advance", 3000, date(2026, 5, 4), cash, food)
        second = _post(db, "dinner 2, advance", 3000, date(2026, 5, 5), cash, food)
        _post(db, "dinner advance, reimburse", 3000, date(2026, 5, 20), food, cash)
        db.commit()

        items = _advance_issue(db)["items"]

        # Two same-amount bills and one settlement: the earlier bill takes it,
        # and the other is left alone rather than pointed at the same row.
        assert [item["transaction_id"] for item in items] == [first.id]
        assert second.id not in {item["transaction_id"] for item in items}
    finally:
        db.close()


def test_a_different_amount_or_a_distant_date_is_not_a_pair() -> None:
    db = _session()
    try:
        cash, food = _accounts(db)
        _post(db, "dinner, advance", 5000, date(2026, 5, 4), cash, food)
        _post(db, "dinner advance, reimburse", 4800, date(2026, 5, 10), food, cash)
        _post(db, "lunch, advance", 2000, date(2026, 1, 4), cash, food)
        _post(db, "lunch advance, reimburse", 2000, date(2026, 6, 30), food, cash)
        db.commit()

        assert _advance_issue(db)["count"] == 0
    finally:
        db.close()


def test_ordinary_spending_is_not_a_pair() -> None:
    db = _session()
    try:
        cash, food = _accounts(db)
        _post(db, "lunch", 1200, date(2026, 5, 4), cash, food)
        _post(db, "lunch", 1200, date(2026, 5, 5), cash, food)
        db.commit()

        assert _advance_issue(db)["count"] == 0
    finally:
        db.close()
