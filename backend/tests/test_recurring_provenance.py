from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.ledger_service import process_transaction
    from backend.app.services.recurring_service import post_recurring_transaction, process_due_for_client
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.ledger_service import process_transaction  # type: ignore[no-redef]
    from app.services.recurring_service import post_recurring_transaction, process_due_for_client  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _setup(db):
    client = models.Client(
        id=1,
        name="provenance-test",
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
        name="Rent expense",
        account_type="expense",
        balance=0,
    )
    db.add_all([client, cash, expense])
    db.flush()
    registry_entry = models.RegistryEntry(
        client_id=1,
        name="recurring owner",
    )
    db.add(registry_entry)
    db.flush()
    recurring = models.RecurringTransaction(
        client_id=1,
        source_registry_entry_id=registry_entry.id,
        name="Rent",
        amount=1000,
        currency="JPY",
        from_account_id=cash.id,
        to_account_id=expense.id,
        frequency="Monthly",
        day_of_month=15,
        next_due_date=date(2026, 5, 15),
        auto_post=True,
        is_active=True,
    )
    db.add(recurring)
    db.flush()
    return recurring, cash, expense


def test_post_recurring_transaction_records_definition():
    db = _session()
    try:
        recurring, _, _ = _setup(db)
        transaction = post_recurring_transaction(db, recurring, date(2026, 5, 15))
        db.commit()
        db.expire_all()
        assert transaction.recurring_transaction_id == recurring.id
        assert transaction.recurring_transaction is recurring
    finally:
        db.close()


def test_catch_up_postings_share_definition():
    db = _session()
    try:
        recurring, _, _ = _setup(db)
        db.commit()
        process_due_for_client(db, 1, today=date(2026, 6, 15))
        transactions = db.query(models.Transaction).order_by(models.Transaction.date).all()
        assert [row.date for row in transactions] == [date(2026, 5, 15), date(2026, 6, 15)]
        assert [row.recurring_transaction_id for row in transactions] == [recurring.id, recurring.id]
    finally:
        db.close()


def test_hand_entered_transaction_has_no_definition():
    db = _session()
    try:
        _, cash, expense = _setup(db)
        transaction = models.Transaction(
            client_id=1,
            date=date(2026, 6, 15),
            description="Hand-entered rent",
            amount=1000,
            currency="JPY",
        )
        db.add(transaction)
        db.flush()
        process_transaction(
            db,
            transaction,
            from_account_id=cash.id,
            to_account_id=expense.id,
        )
        db.expire_all()
        assert transaction.recurring_transaction_id is None
        assert db.query(models.JournalEntry).filter_by(transaction_id=transaction.id).count() == 2
    finally:
        db.close()


def test_deleting_definition_preserves_posting_without_sqlite_fk_enforcement():
    db = _session()
    try:
        recurring, _, _ = _setup(db)
        transaction = post_recurring_transaction(db, recurring, date(2026, 5, 15))
        db.commit()
        recurring_id = recurring.id
        transaction_id = transaction.id
        db.delete(recurring)
        db.commit()
        db.expire_all()
        posted = db.query(models.Transaction).one()
        assert posted.id == transaction_id
        assert db.query(models.JournalEntry).filter_by(transaction_id=transaction_id).count() == 2
        assert db.get(models.RecurringTransaction, recurring_id) is None
        assert posted.recurring_transaction is None
        # This fixture leaves SQLite FKs off, so PostgreSQL's SET NULL does not run.
        assert posted.recurring_transaction_id == recurring_id
        foreign_key = next(iter(models.Transaction.__table__.c.recurring_transaction_id.foreign_keys))
        assert foreign_key.ondelete == "SET NULL"
    finally:
        db.close()
