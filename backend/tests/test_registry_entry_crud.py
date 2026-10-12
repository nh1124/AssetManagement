from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.domain.errors import Invalid
from backend.app.routers.exchange_rates import create_exchange_rate
from backend.app.services import registry_service


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    # Deleting a definition relies on the schema's own ON DELETE rules, which
    # SQLite ignores unless asked. Without this the test would pass on
    # behaviour Postgres does not have.
    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add_all([
        models.Client(id=1, name="test", general_settings={}, ai_config={}),
        models.Client(id=2, name="other", general_settings={}, ai_config={}),
        models.Account(client_id=1, name="bank", account_type="asset"),
        models.Account(client_id=1, name="subscriptions", account_type="expense"),
        models.Account(client_id=2, name="other bank", account_type="asset"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _data(db, **changes):
    accounts = {row.name: row.id for row in db.query(models.Account).all()}
    return schemas.RegistryEntryCreate(**(dict(
        name="subscription", amount=1200, frequency="Monthly",
        source_account_id=accounts["bank"], destination_account_id=accounts["subscriptions"],
        budget_account_id=accounts["subscriptions"], generate_recurring=True, budget_active=False,
    ) | changes)).model_dump()


def test_create_entry_writes_one_registry_and_one_recurring_linked_both_ways(db):
    entry = registry_service.create_entry(db, 1, _data(db))
    db.expire_all()
    saved = db.query(models.RegistryEntry).one()
    recurring = db.query(models.RecurringTransaction).one()
    assert saved.id == entry.id == recurring.source_registry_entry_id
    assert saved.source_recurring_transaction_id == recurring.id
    assert saved.budget_active is True
    assert (recurring.name, recurring.amount, recurring.from_account_id, recurring.to_account_id) == (
        saved.name, saved.amount, saved.source_account_id, saved.destination_account_id,
    )


def test_update_entry_unknown_id_returns_none_and_writes_nothing(db):
    # Missing entries are resolved before account validation, as in the router.
    assert registry_service.update_entry(db, 1, 999, {"source_account_id": 999}) is None
    assert db.query(models.RegistryEntry).count() == 0
    assert db.query(models.RecurringTransaction).count() == 0
    assert not db.new and not db.dirty and not db.deleted


def test_update_entry_preserves_the_one_to_one_recurring_link(db):
    entry = registry_service.create_entry(db, 1, _data(db))
    entry_id, recurring_id = entry.id, entry.source_recurring_transaction_id
    updated = registry_service.update_entry(
        db, 1, entry_id, _data(db, name="updated", amount=2500, day_of_month=14),
    )
    db.expire_all()
    saved = db.query(models.RegistryEntry).one()
    recurring = db.query(models.RecurringTransaction).one()
    assert updated.id == saved.id == entry_id == recurring.source_registry_entry_id
    assert saved.source_recurring_transaction_id == recurring.id == recurring_id
    assert saved.budget_active is True
    assert (recurring.name, recurring.amount, recurring.day_of_month) == ("updated", 2500, 14)
    assert (saved.name, saved.amount, saved.day_of_month) == ("updated", 2500, 14)


def test_delete_entry_removes_the_definition_and_all_linked_recurring_rows(db):
    """X2: DELETE deletes. It used to drop three flags and keep the row.

    The old behaviour left an entry no reader could see -- every query filters
    on is_active -- while it still held its name, so the same subscription
    could not be registered again under the same identity.
    """
    entry = registry_service.create_entry(db, 1, _data(db))
    entry_id = entry.id
    # Legacy duplicates must also disappear with their definition.
    db.add(models.RecurringTransaction(client_id=1, source_registry_entry_id=entry_id))
    db.commit()
    assert db.query(models.RecurringTransaction).count() == 2
    assert registry_service.delete_entry(db, 1, entry_id) is True
    db.expire_all()
    assert db.query(models.RegistryEntry).count() == 0
    assert db.query(models.RecurringTransaction).count() == 0
    assert registry_service.delete_entry(db, 1, entry_id) is False
    assert registry_service.delete_entry(db, 1, 999) is False


def test_re_registering_after_a_delete_leaves_no_ghost(db):
    """A deactivated row was invisible to readers but still exported and imported.

    Re-registering the same subscription used to leave two rows behind, one of
    them reachable only through a backup.
    """
    first = registry_service.create_entry(db, 1, _data(db))
    assert registry_service.delete_entry(db, 1, first.id) is True
    second = registry_service.create_entry(db, 1, _data(db))
    assert db.query(models.RegistryEntry).one().id == second.id
    assert db.query(models.RecurringTransaction).one().source_registry_entry_id == second.id


def test_delete_entry_keeps_postings_the_recurring_row_already_made(db):
    """Deleting a definition must not rewrite history, only unlink it."""
    entry = registry_service.create_entry(db, 1, _data(db))
    recurring_id = entry.source_recurring_transaction_id
    accounts = {row.name: row.id for row in db.query(models.Account).filter_by(client_id=1)}
    posted = models.Transaction(
        client_id=1, date=date(2026, 10, 1), description="subscription",
        amount_minor=1200, currency="JPY", recurring_transaction_id=recurring_id,
    )
    db.add(posted)
    db.commit()
    db.add_all([
        models.JournalEntry(transaction_id=posted.id, account_id=accounts["subscriptions"],
                            debit_minor=1200, credit_minor=0),
        models.JournalEntry(transaction_id=posted.id, account_id=accounts["bank"],
                            debit_minor=0, credit_minor=1200),
    ])
    db.commit()
    posted_id = posted.id

    assert registry_service.delete_entry(db, 1, entry.id) is True
    db.expire_all()
    survivor = db.query(models.Transaction).one()
    assert survivor.id == posted_id
    assert survivor.amount_minor == 1200
    assert db.query(models.JournalEntry).count() == 2
    # The provenance is gone because its cause is; the money is not.
    assert survivor.recurring_transaction_id is None


@pytest.mark.parametrize("key", ["budget_account_id", "source_account_id", "destination_account_id"])
def test_validate_account_refs_rejects_another_clients_account_with_existing_http_error(db, key):
    foreign_id = db.query(models.Account).filter_by(client_id=2).one().id
    with pytest.raises(Invalid) as error:
        registry_service.validate_account_refs(db, 1, {key: foreign_id})
    assert str(error.value) == f"{key} must belong to this client"
    assert db.query(models.RegistryEntry).count() == 0
    assert db.query(models.RecurringTransaction).count() == 0
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_registry_crud_commit_false_leaves_entry_and_recurring_changes_rollbackable(db, operation):
    if operation == "create":
        entry = registry_service.create_entry(db, 1, _data(db), commit=False)
        assert entry.source_recurring_transaction_id is not None
        assert db.query(models.RecurringTransaction).count() == 1
        db.rollback()
        assert db.query(models.RegistryEntry).count() == 0
        assert db.query(models.RecurringTransaction).count() == 0
        return

    entry = registry_service.create_entry(db, 1, _data(db))
    entry_id, recurring_id = entry.id, entry.source_recurring_transaction_id
    if operation == "update":
        registry_service.update_entry(db, 1, entry_id, _data(db, amount=2500), commit=False)
        assert db.get(models.RecurringTransaction, recurring_id).amount == 2500
    else:
        assert registry_service.delete_entry(db, 1, entry_id, commit=False) is True
        assert db.query(models.RecurringTransaction).count() == 0
    db.rollback()
    saved = db.get(models.RegistryEntry, entry_id)
    recurring = db.query(models.RecurringTransaction).one()
    assert saved.amount == recurring.amount == 1200
    assert saved.is_active is True
    assert saved.source_recurring_transaction_id == recurring.id == recurring_id
    assert recurring.source_registry_entry_id == entry_id


def test_exchange_rate_post_preserves_manual_upsert_row_and_metadata(db):
    client = db.get(models.Client, 1)
    payload = dict(
        base_currency=" usd ", quote_currency=" jpy ", rate=150,
        as_of_date="2026-10-11", source="",
    )
    first = create_exchange_rate(schemas.ExchangeRateCreate(**payload), db, client)
    assert (first["base_currency"], first["quote_currency"], first["source"]) == (
        "USD", "JPY", "manual",
    )
    second = create_exchange_rate(
        schemas.ExchangeRateCreate(**(payload | {"rate": 151, "source": "custom"})), db, client,
    )
    assert second["id"] == first["id"]
    assert second["created_at"] == first["created_at"]
    assert (second["rate"], second["source"]) == (151, "custom")
    with pytest.raises(HTTPException) as error:
        create_exchange_rate(
            schemas.ExchangeRateCreate(**(payload | {"quote_currency": "USD"})), db, client,
        )
    assert error.value.status_code == 400
    assert error.value.detail == "Currencies must differ"
    db.rollback()
    db.expire_all()
    saved = db.query(models.ExchangeRate).one()
    assert saved.id == first["id"]
    assert (saved.client_id, saved.base_currency, saved.quote_currency, saved.as_of_date) == (
        1, "USD", "JPY", date(2026, 10, 11),
    )
    assert (saved.rate, saved.source) == (151, "custom")
