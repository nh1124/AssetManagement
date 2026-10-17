from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.domain.errors import Conflict
from backend.app.routers import recurring as recurring_router
from backend.app.services import recurring_service, registry_service


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add_all([
        models.Client(id=1, name="test", general_settings={}),
        models.Client(id=2, name="other", general_settings={}),
        models.Account(client_id=1, name="bank", account_type="asset"),
        models.Account(client_id=1, name="rent", account_type="expense"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _recurring(db, *, client_id=1, **changes):
    accounts = {row.name: row.id for row in db.query(models.Account).all()}
    payload = dict(
        name="Rent", amount=1000, currency="JPY", frequency="Monthly", day_of_month=31,
        from_account_id=accounts["bank"], to_account_id=accounts["rent"],
        next_due_date=date(2026, 2, 28),
    ) | changes
    return registry_service.upsert_registry_from_recurring_payload(
        db, client_id, payload, commit=True,
    )


def test_process_one_posts_one_transaction_and_advances_by_schedule(db):
    recurring = _recurring(db)
    transaction, next_due_date = recurring_service.process_one(db, recurring)
    db.expire_all()
    saved = db.query(models.Transaction).one()
    assert saved.id == transaction.id
    assert (saved.date, saved.amount, saved.recurring_transaction_id) == (
        date(2026, 2, 28), 1000, recurring.id,
    )
    assert db.query(models.JournalEntry).filter_by(transaction_id=saved.id).count() == 2
    assert recurring.next_due_date == next_due_date == date(2026, 3, 31)


@pytest.mark.parametrize("refusal,message", [
    ("inactive", "Recurring transaction is inactive"),
    ("past_end", "Recurring transaction is past its end period"),
])
def test_process_one_refusals_write_nothing_and_keep_http_409(db, refusal, message):
    recurring = _recurring(db)
    if refusal == "inactive":
        recurring.is_active = False
    else:
        recurring.end_period = "2026-01"
    db.commit()
    before = {column.name: getattr(recurring, column.name) for column in recurring.__table__.columns}
    with pytest.raises(recurring_service.RecurringNotPostable, match=f"^{message}$"):
        recurring_service.process_one(db, recurring)
    with pytest.raises(recurring_service.RecurringNotPostable) as error:
        recurring_router.process_recurring_transaction(recurring.id, db, db.get(models.Client, 1))
    # test_domain_errors.py pins Conflict to 409 over HTTP.
    assert isinstance(error.value, Conflict)
    assert str(error.value) == message
    assert db.query(models.Transaction).count() == db.query(models.JournalEntry).count() == 0
    assert before == {column.name: getattr(recurring, column.name) for column in recurring.__table__.columns}
    assert not db.new and not db.dirty and not db.deleted


def test_process_one_without_due_date_posts_dated_today(db, monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 2, 12)

    monkeypatch.setattr(recurring_service, "date", FixedDate)
    recurring = _recurring(db, next_due_date=None)
    transaction, next_due_date = recurring_service.process_one(db, recurring)
    assert transaction.date == date(2026, 2, 12)
    assert next_due_date == date(2026, 3, 31)


def test_skip_one_advances_schedule_without_posting(db):
    recurring = _recurring(db)
    next_due_date = recurring_service.skip_one(db, recurring)
    db.expire_all()
    assert recurring.next_due_date == next_due_date == date(2026, 3, 31)
    assert db.query(models.Transaction).count() == db.query(models.JournalEntry).count() == 0


def test_delete_recurring_detaches_first_and_preserves_registry_entry(db, monkeypatch):
    recurring = _recurring(db)
    entry_id = recurring.source_registry_entry_id
    entry = db.get(models.RegistryEntry, entry_id)
    delete = db.delete
    detached = []

    def delete_after_detach(row):
        detached.append((entry.source_recurring_transaction_id, entry.generate_recurring))
        delete(row)

    monkeypatch.setattr(db, "delete", delete_after_detach)
    registry_service.delete_recurring(db, recurring)
    db.expire_all()
    saved = db.query(models.RegistryEntry).one()
    assert detached == [(None, False)]
    assert saved.id == entry_id
    assert saved.source_recurring_transaction_id is None
    assert (saved.generate_recurring, saved.is_active, saved.budget_active) == (False, True, True)
    assert db.query(models.RecurringTransaction).count() == 0


def test_list_due_includes_only_client_active_rows_due_on_or_before_date(db):
    earlier = _recurring(db, next_due_date=date(2026, 2, 27))
    today = _recurring(db)
    _recurring(db, next_due_date=date(2026, 3, 1))
    _recurring(db, is_active=False)
    _recurring(db, next_due_date=None)
    _recurring(db, client_id=2)
    assert {row.id for row in recurring_service.list_due(db, 1, date(2026, 2, 28))} == {
        earlier.id, today.id,
    }


def test_reads_scope_by_client_and_list_serializes_registry_name_without_session(db, monkeypatch):
    recurring = _recurring(db)
    _recurring(db, client_id=2)
    client = db.get(models.Client, 1)
    assert recurring_service.get_for_client(db, 1, recurring.id) is recurring
    assert recurring_service.get_for_client(db, 2, recurring.id) is None
    assert recurring_service.get_for_client(db, 1, 999) is None
    db.expunge_all()
    rows = recurring_service.list_for_client(db, 1)
    assert [row.id for row in rows] == [recurring.id]
    db.expunge_all()
    monkeypatch.setattr(recurring_router, "list_for_client", lambda db, client_id: rows)
    response = recurring_router.get_recurring_transactions(db, client)
    assert response == [{
        **{field: getattr(rows[0], field) for field in (
            "id", "client_id", "name", "currency", "from_account_id", "to_account_id",
            "frequency", "day_of_month", "month_of_year", "next_due_date", "start_period",
            "end_period", "auto_post", "is_active", "source_registry_entry_id", "created_at",
        )},
        "amount": 1000.0,
        "source_registry_entry_name": "Rent",
    }]


def test_process_one_rolls_back_posting_and_schedule_on_failure(db, monkeypatch):
    recurring = _recurring(db)
    advance = recurring_service.advance_next_due_date

    def fail_after_advance(row):
        advance(row)
        raise ValueError("posting failed")

    monkeypatch.setattr(recurring_service, "advance_next_due_date", fail_after_advance)
    with pytest.raises(ValueError, match="^posting failed$"):
        recurring_router.process_recurring_transaction(recurring.id, db, db.get(models.Client, 1))
    assert recurring.next_due_date == date(2026, 2, 28)
    assert db.query(models.Transaction).count() == db.query(models.JournalEntry).count() == 0


@pytest.mark.parametrize("operation", ["process", "skip", "delete"])
def test_commit_false_leaves_posting_schedule_and_deletion_rollbackable(db, operation):
    recurring = _recurring(db)
    recurring_id, entry_id = recurring.id, recurring.source_registry_entry_id
    if operation == "process":
        transaction, due = recurring_service.process_one(db, recurring, commit=False)
        assert transaction.id is not None
        assert due == date(2026, 3, 31)
    elif operation == "skip":
        assert recurring_service.skip_one(db, recurring, commit=False) == date(2026, 3, 31)
    else:
        registry_service.delete_recurring(db, recurring, commit=False)
        assert db.query(models.RecurringTransaction).count() == 0
    db.rollback()
    saved = db.get(models.RecurringTransaction, recurring_id)
    assert saved.next_due_date == date(2026, 2, 28)
    assert saved.source_registry_entry_id == entry_id
    assert db.get(models.RegistryEntry, entry_id).source_recurring_transaction_id == recurring_id
    assert db.query(models.Transaction).count() == db.query(models.JournalEntry).count() == 0


def test_upsert_default_still_flushes_and_explicit_commit_persists(db):
    recurring = registry_service.upsert_registry_from_recurring_payload(db, 1, {"name": "pending"})
    assert recurring.id is not None
    db.rollback()
    assert db.query(models.RecurringTransaction).count() == db.query(models.RegistryEntry).count() == 0
    db.expunge_all()
    registry_service.upsert_registry_from_recurring_payload(db, 1, {"name": "saved"}, commit=True)
    db.rollback()
    assert db.query(models.RecurringTransaction).one().name == "saved"
    assert db.query(models.RegistryEntry).one().name == "saved"


def test_router_preserves_process_skip_and_delete_response_dicts(db):
    recurring = _recurring(db)
    recurring_id = recurring.id
    client = db.get(models.Client, 1)
    processed = recurring_router.process_recurring_transaction(recurring_id, db, client)
    assert processed == {
        "message": "Transaction processed",
        "transaction_id": db.query(models.Transaction).one().id,
        "next_due_date": date(2026, 3, 31),
    }
    assert recurring_router.skip_recurring_transaction(recurring_id, db, client) == {
        "message": "Recurring transaction skipped", "next_due_date": date(2026, 4, 30),
    }
    assert recurring_router.delete_recurring_transaction(recurring_id, db, client) == {
        "message": "Recurring transaction deleted",
    }
