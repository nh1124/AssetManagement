from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.ledger_service import Leg, create_transaction, delete_transaction
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.ledger_service import Leg, create_transaction, delete_transaction  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


@pytest.fixture
def posting():
    db = _session()
    client = models.Client(
        id=1,
        name="delete-transaction-test",
        general_settings={},
        ai_config={},
    )
    cash = models.Account(
        client_id=1,
        name="Cash",
        account_type="asset",
        balance=10000,
    )
    expense = models.Account(
        client_id=1,
        name="Food",
        account_type="expense",
        balance=0,
    )
    advance = models.Account(
        client_id=1,
        name="Advance",
        account_type="asset",
        balance=0,
    )
    db.add_all([client, cash, expense, advance])
    db.commit()
    try:
        yield db, cash, expense, advance
    finally:
        db.close()


def _create(db, **kwargs):
    return create_transaction(
        db,
        client_id=1,
        date=date(2026, 10, 10),
        description="Lunch",
        amount=1000,
        currency="JPY",
        **kwargs,
    )


def test_deletes_row_and_both_legs_without_affecting_other_transaction(posting):
    db, cash, expense, _ = posting
    tx = _create(
        db,
        from_account_id=cash.id,
        to_account_id=expense.id,
    )
    other = _create(
        db,
        from_account_id=cash.id,
        to_account_id=expense.id,
    )
    db.commit()
    tx_id, other_id = tx.id, other.id
    other_legs = db.query(models.JournalEntry).filter_by(transaction_id=other_id).all()
    expected = sorted((leg.id, leg.account_id, leg.debit, leg.credit) for leg in other_legs)
    assert len(expected) == 2

    delete_transaction(db, tx)
    db.commit()

    assert db.get(models.Transaction, tx_id) is None
    assert db.query(models.JournalEntry).filter_by(transaction_id=tx_id).count() == 0
    assert db.get(models.Transaction, other_id) is other
    remaining = db.query(models.JournalEntry).filter_by(transaction_id=other_id).all()
    assert sorted((leg.id, leg.account_id, leg.debit, leg.credit) for leg in remaining) == expected


def test_delete_restores_cached_balances(posting):
    db, cash, expense, _ = posting
    before = cash.balance, expense.balance
    tx = _create(
        db,
        from_account_id=cash.id,
        to_account_id=expense.id,
    )
    db.commit()
    assert (cash.balance, expense.balance) != before

    delete_transaction(db, tx)
    db.commit()
    db.refresh(cash)
    db.refresh(expense)

    assert (cash.balance, expense.balance) == before


def test_caller_can_rollback_deletion(posting):
    db, cash, expense, _ = posting
    tx = _create(
        db,
        from_account_id=cash.id,
        to_account_id=expense.id,
    )
    db.commit()
    tx_id = tx.id
    entries = db.query(models.JournalEntry).filter_by(transaction_id=tx_id).all()
    expected = sorted((leg.id, leg.account_id, leg.debit, leg.credit) for leg in entries)
    assert len(expected) == 2
    balances = cash.balance, expense.balance

    delete_transaction(db, tx)
    db.rollback()

    assert db.get(models.Transaction, tx_id) is not None
    restored = db.query(models.JournalEntry).filter_by(transaction_id=tx_id).all()
    assert sorted((leg.id, leg.account_id, leg.debit, leg.credit) for leg in restored) == expected
    assert (cash.balance, expense.balance) == balances


def test_deletes_all_three_compound_legs(posting):
    db, cash, expense, advance = posting
    tx = _create(
        db,
        legs=[
            Leg(
                account_id=expense.id,
                debit=600,
            ),
            Leg(
                account_id=advance.id,
                debit=400,
            ),
            Leg(
                account_id=cash.id,
                credit=1000,
            ),
        ],
    )
    db.commit()
    tx_id = tx.id
    assert db.query(models.JournalEntry).filter_by(transaction_id=tx_id).count() == 3

    delete_transaction(db, tx)
    db.commit()

    assert db.get(models.Transaction, tx_id) is None
    assert db.query(models.JournalEntry).filter_by(transaction_id=tx_id).count() == 0
