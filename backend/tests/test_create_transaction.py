from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.ledger_service import Leg, create_transaction
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.ledger_service import Leg, create_transaction  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


@pytest.fixture
def posting():
    db = _session()
    client = models.Client(
        id=1,
        name="create-transaction-test",
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


def test_creates_row_and_both_legs(posting):
    db, cash, expense, _ = posting
    tx = _create(db, from_account_id=cash.id, to_account_id=expense.id)
    assert tx.id is not None
    db.flush()
    assert db.query(models.Transaction).one() is tx
    entries = db.query(models.JournalEntry).filter_by(transaction_id=tx.id).all()
    assert sorted((row.account_id, row.debit, row.credit) for row in entries) == sorted([
        (expense.id, 1000, 0),
        (cash.id, 0, 1000),
    ])


def test_compound_legs_without_account_pair(posting):
    db, cash, expense, advance = posting
    tx = _create(db, legs=[
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
    ])
    db.flush()
    entries = db.query(models.JournalEntry).filter_by(transaction_id=tx.id).all()
    assert sorted((row.account_id, row.debit, row.credit) for row in entries) == sorted([
        (expense.id, 600, 0),
        (advance.id, 400, 0),
        (cash.id, 0, 1000),
    ])


def test_dropped_category_is_rejected_before_construction(posting):
    db, cash, expense, _ = posting
    with pytest.raises(TypeError, match="category.*transactions"):
        _create(db, from_account_id=cash.id, to_account_id=expense.id, category="food")
    assert db.query(models.Transaction).count() == 0
    assert not db.new


def test_caller_can_rollback(posting):
    db, cash, expense, _ = posting
    _create(db, from_account_id=cash.id, to_account_id=expense.id)
    db.rollback()
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.JournalEntry).count() == 0


def test_recurring_provenance_passes_through(posting):
    db, cash, expense, _ = posting
    registry = models.RegistryEntry(
        client_id=1,
        name="Lunch owner",
    )
    db.add(registry)
    db.flush()
    recurring = models.RecurringTransaction(
        client_id=1,
        source_registry_entry_id=registry.id,
        name="Lunch",
        amount=1000,
        currency="JPY",
        from_account_id=cash.id,
        to_account_id=expense.id,
        frequency="Monthly",
        day_of_month=10,
    )
    db.add(recurring)
    db.flush()
    tx = _create(
        db,
        from_account_id=cash.id,
        to_account_id=expense.id,
        recurring_transaction_id=recurring.id,
    )
    db.flush()
    db.expire_all()
    assert db.query(models.Transaction).one().recurring_transaction_id == recurring.id
    assert tx.recurring_transaction is recurring


def test_unbalanced_legs_still_raise(posting):
    db, cash, expense, _ = posting
    with pytest.raises(ValueError, match="does not balance"):
        _create(db, legs=[Leg(account_id=expense.id, debit=1000), Leg(account_id=cash.id, credit=900)])
