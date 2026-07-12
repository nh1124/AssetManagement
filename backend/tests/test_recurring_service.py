from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.main import backfill_recurring_next_due_dates
    from backend.app.services.recurring_service import (
        advance_next_due_date,
        compute_next_due_date,
        ensure_next_due_date,
        process_due_for_client,
    )
    from backend.app.services.registry_service import sync_recurring_from_registry
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.main import backfill_recurring_next_due_dates  # type: ignore[no-redef]
    from app.services.recurring_service import (  # type: ignore[no-redef]
        advance_next_due_date,
        compute_next_due_date,
        ensure_next_due_date,
        process_due_for_client,
    )
    from app.services.registry_service import sync_recurring_from_registry  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client_and_accounts(db):
    client = models.Client(id=1, name="recurring-test", general_settings={}, ai_config={})
    cash = models.Account(client_id=1, name="Cash", account_type="asset", balance=10000)
    expense = models.Account(client_id=1, name="Rent expense", account_type="expense", balance=0)
    db.add_all([client, cash, expense])
    db.flush()
    return client, cash, expense


def _recurring(db, cash, expense, **overrides):
    values = {
        "client_id": 1,
        "name": "Rent",
        "amount": 1000,
        "currency": "JPY",
        "type": "Expense",
        "from_account_id": cash.id,
        "to_account_id": expense.id,
        "frequency": "Monthly",
        "day_of_month": 15,
        "auto_post": True,
        "is_active": True,
    }
    values.update(overrides)
    recurring = models.RecurringTransaction(**values)
    db.add(recurring)
    db.flush()
    return recurring


def test_compute_next_due_date_clamps_month_end_and_honors_start_period():
    recurring = models.RecurringTransaction(frequency="Monthly", day_of_month=31)
    assert compute_next_due_date(recurring, date(2026, 2, 1)) == date(2026, 2, 28)
    assert compute_next_due_date(recurring, date(2028, 2, 1)) == date(2028, 2, 29)

    recurring.start_period = "2026-09"
    assert compute_next_due_date(recurring, date(2026, 2, 1)) == date(2026, 9, 30)


def test_compute_next_due_date_yearly_uses_month_of_year():
    recurring = models.RecurringTransaction(
        frequency="Yearly",
        day_of_month=31,
        month_of_year=3,
    )
    assert compute_next_due_date(recurring, date(2026, 4, 1)) == date(2027, 3, 31)


def test_ensure_next_due_date_does_not_rewind_existing_value():
    recurring = models.RecurringTransaction(
        frequency="Monthly",
        day_of_month=1,
        next_due_date=date(2027, 1, 1),
    )
    ensure_next_due_date(recurring, date(2026, 1, 1))
    assert recurring.next_due_date == date(2027, 1, 1)


def test_advance_next_due_date_restores_day_after_short_month():
    recurring = models.RecurringTransaction(
        frequency="Monthly",
        day_of_month=31,
        next_due_date=date(2026, 2, 28),
    )
    advance_next_due_date(recurring)
    assert recurring.next_due_date == date(2026, 3, 31)


def test_process_due_creates_transaction_and_two_journal_entries():
    db = _session()
    try:
        _, cash, expense = _client_and_accounts(db)
        recurring = _recurring(db, cash, expense, next_due_date=date(2026, 6, 15))
        db.commit()

        result = process_due_for_client(db, 1, today=date(2026, 6, 15))

        assert len(result["processed"]) == 1
        transaction = db.query(models.Transaction).one()
        assert transaction.date == date(2026, 6, 15)
        assert transaction.category == "Rent expense"
        assert db.query(models.JournalEntry).filter_by(transaction_id=transaction.id).count() == 2
        assert recurring.next_due_date == date(2026, 7, 15)
    finally:
        db.close()


def test_process_due_catches_up_and_is_idempotent_on_same_day():
    db = _session()
    try:
        _, cash, expense = _client_and_accounts(db)
        recurring = _recurring(db, cash, expense, next_due_date=date(2026, 4, 15))
        db.commit()

        process_due_for_client(db, 1, today=date(2026, 6, 15))
        assert [row.date for row in db.query(models.Transaction).order_by(models.Transaction.date).all()] == [
            date(2026, 4, 15),
            date(2026, 5, 15),
            date(2026, 6, 15),
        ]
        assert recurring.next_due_date == date(2026, 7, 15)

        second = process_due_for_client(db, 1, today=date(2026, 6, 15))
        assert second == {"processed": [], "deactivated": []}
        assert db.query(models.Transaction).count() == 3
    finally:
        db.close()


def test_process_due_limits_each_recurring_to_24_periods():
    db = _session()
    try:
        _, cash, expense = _client_and_accounts(db)
        recurring = _recurring(db, cash, expense, next_due_date=date(2024, 1, 15))
        db.commit()

        process_due_for_client(db, 1, today=date(2026, 12, 15))

        assert db.query(models.Transaction).count() == 24
        assert recurring.next_due_date == date(2026, 1, 15)
    finally:
        db.close()


def test_process_due_deactivates_past_end_period_and_syncs_registry():
    db = _session()
    try:
        _client_and_accounts(db)
        entry = models.RegistryEntry(
            client_id=1,
            name="Ended rent",
            amount=1000,
            currency="JPY",
            frequency="Monthly",
            day_of_month=15,
            transaction_type="Expense",
            line_type="expense",
            generate_recurring=True,
            budget_active=True,
            is_active=True,
            end_period="2026-05",
        )
        db.add(entry)
        db.flush()
        sync_recurring_from_registry(db, entry)
        db.flush()
        recurring = db.query(models.RecurringTransaction).one()
        recurring.next_due_date = date(2026, 6, 15)
        db.commit()

        result = process_due_for_client(db, 1, today=date(2026, 6, 15))

        assert result["deactivated"] == [recurring.id]
        assert recurring.is_active is False
        assert entry.is_active is False
        assert db.query(models.Transaction).count() == 0
    finally:
        db.close()


def test_process_due_ignores_manual_recurring():
    db = _session()
    try:
        _, cash, expense = _client_and_accounts(db)
        _recurring(
            db,
            cash,
            expense,
            next_due_date=date(2026, 6, 15),
            auto_post=False,
        )
        db.commit()
        assert process_due_for_client(db, 1, today=date(2026, 6, 15)) == {
            "processed": [],
            "deactivated": [],
        }
        assert db.query(models.Transaction).count() == 0
    finally:
        db.close()


def test_registry_sync_initializes_due_date_and_preserves_progress():
    db = _session()
    try:
        _client_and_accounts(db)
        entry = models.RegistryEntry(
            client_id=1,
            name="Registry rent",
            amount=1000,
            currency="JPY",
            frequency="Monthly",
            day_of_month=10,
            transaction_type="Expense",
            line_type="expense",
            generate_recurring=True,
            budget_active=True,
            is_active=True,
        )
        db.add(entry)
        db.flush()

        sync_recurring_from_registry(db, entry)
        db.flush()
        recurring = db.query(models.RecurringTransaction).one()
        assert recurring.next_due_date is not None

        recurring.next_due_date = date(2030, 1, 10)
        sync_recurring_from_registry(db, entry)
        assert recurring.next_due_date == date(2030, 1, 10)
    finally:
        db.close()


def test_startup_backfill_initializes_active_null_due_rows_only():
    db = _session()
    try:
        _, cash, expense = _client_and_accounts(db)
        active = _recurring(db, cash, expense, next_due_date=None)
        inactive = _recurring(db, cash, expense, name="Inactive", next_due_date=None, is_active=False)
        db.commit()

        assert backfill_recurring_next_due_dates(db, today=date(2026, 7, 12)) == 1
        assert active.next_due_date == date(2026, 7, 15)
        assert inactive.next_due_date is None
    finally:
        db.close()
