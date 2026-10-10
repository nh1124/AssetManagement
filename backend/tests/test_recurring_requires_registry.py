import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.routers.data_transfer import ImportPayload, import_client_data
    from backend.app.services.registry_service import upsert_registry_from_recurring_payload
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.routers.data_transfer import ImportPayload, import_client_data  # type: ignore[no-redef]
    from app.services.registry_service import upsert_registry_from_recurring_payload  # type: ignore[no-redef]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add(models.Client(
        id=1,
        name="test",
        general_settings={},
        ai_config={},
    ))
    session.flush()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_recurring_without_registry_cannot_be_persisted(db):
    db.add(models.RecurringTransaction(
        client_id=1,
        name="unowned",
    ))
    with pytest.raises(IntegrityError, match="NOT NULL"):
        db.flush()
    db.rollback()


def test_registry_sync_has_owner_at_first_insert(db):
    inserted_sources = []

    def capture_insert(mapper, connection, target):
        inserted_sources.append(target.source_registry_entry_id)

    event.listen(models.RecurringTransaction, "before_insert", capture_insert)
    try:
        recurring = upsert_registry_from_recurring_payload(db, 1, {
            "name": "subscription",
            "amount": 1200,
            "frequency": "Monthly",
        })
    finally:
        event.remove(models.RecurringTransaction, "before_insert", capture_insert)
    entry = db.get(models.RegistryEntry, recurring.source_registry_entry_id)
    assert entry is not None
    assert recurring.source_registry_entry_id == entry.id
    assert inserted_sources == [entry.id]
    assert entry.source_recurring_transaction_id == recurring.id


def test_registry_owner_foreign_key_cascades():
    foreign_key = next(iter(models.RecurringTransaction.__table__.c.source_registry_entry_id.foreign_keys))
    # This SQLite fixture leaves FKs off, so it cannot exercise PostgreSQL's cascade.
    assert foreign_key.ondelete == "CASCADE"


def test_import_restores_registry_before_definitions_and_skips_unowned(db):
    result = import_client_data(ImportPayload(data={
        "registry_entries": [
            {"id": 10, "name": "owner", "source_recurring_transaction_id": 20},
            {"id": 11, "name": "skipped owner", "source_recurring_transaction_id": 21},
        ],
        "recurring_transactions": [
            {"id": 20, "name": "owned", "frequency": "Monthly", "source_registry_entry_id": 10},
            {"id": 21, "name": "legacy", "frequency": "Monthly"},
            {"id": 22, "name": "missing", "frequency": "Monthly", "source_registry_entry_id": 999},
        ],
    }), db, db.get(models.Client, 1))
    recurring = db.query(models.RecurringTransaction).one()
    entries = {row.name: row for row in db.query(models.RegistryEntry).all()}
    assert recurring.source_registry_entry_id == entries["owner"].id
    assert entries["owner"].source_recurring_transaction_id == recurring.id
    assert entries["skipped owner"].source_recurring_transaction_id is None
    warning = next(row for row in result["validation"]["issues"] if row["code"] == "recurring_without_registry_skipped")
    assert warning["severity"] == "warning"
    assert warning["collection"] == "recurring_transactions"
    assert warning["detail"] == "Skipped 2 recurring definitions without a restorable registry entry."
    assert result["validation"]["warning_count"] == len(result["validation"]["issues"])
