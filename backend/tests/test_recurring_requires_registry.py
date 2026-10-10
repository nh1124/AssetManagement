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


def test_import_restores_registry_before_definitions_and_backfills_unowned(db):
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
    definitions = {row.name: row for row in db.query(models.RecurringTransaction).all()}
    assert len(definitions) == 3
    recurring = definitions["owned"]
    entries = {row.name: row for row in db.query(models.RegistryEntry).all()}
    assert recurring.source_registry_entry_id == entries["owner"].id
    assert entries["owner"].source_recurring_transaction_id == recurring.id
    assert entries["skipped owner"].source_recurring_transaction_id == definitions["legacy"].id
    for name in ("legacy", "missing"):
        entry = db.get(models.RegistryEntry, definitions[name].source_registry_entry_id)
        assert entry.source_recurring_transaction_id == definitions[name].id
        assert entry.generate_recurring is True
        assert entry.budget_active is True
        assert entry.source_account_id is None
        assert entry.destination_account_id is None
    warning = next(row for row in result["validation"]["issues"] if row["code"] == "recurring_without_registry_backfilled")
    assert warning["severity"] == "warning"
    assert warning["collection"] == "recurring_transactions"
    assert warning["detail"] == "Created registry entries for 2 recurring definitions without a restorable registry entry."
    assert result["validation"]["warning_count"] == len(result["validation"]["issues"])


def test_import_bulk_registry_wipe_cascades_existing_owned_definitions():
    # A local engine enforces foreign keys without changing the shared fixtures.
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )()
    try:
        session.add(models.Client(
            id=1,
            name="test",
            general_settings={},
            ai_config={},
        ))
        session.flush()
        upsert_registry_from_recurring_payload(session, 1, {"name": "old subscription"})
        session.commit()
        session.expunge_all()
        result = import_client_data(ImportPayload(data={
            "registry_entries": [{"id": 10, "name": "restored owner", "source_recurring_transaction_id": 20}],
            "recurring_transactions": [{"id": 20, "name": "restored subscription", "frequency": "Monthly", "source_registry_entry_id": 10}],
        }), session, session.get(models.Client, 1))
        assert result["validation"]["error_count"] == 0
        entry = session.query(models.RegistryEntry).one()
        recurring = session.query(models.RecurringTransaction).one()
        assert entry.name == "restored owner"
        assert recurring.name == "restored subscription"
        assert recurring.source_registry_entry_id == entry.id
        assert entry.source_recurring_transaction_id == recurring.id
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("source_type,destination_type,kind,line_type,entry_type,budgeted", [
    ("asset", "expense", None, "expense", "service", True),
    ("asset", "liability", "loan", "debt_payment", "debt", True),
    ("income", "asset", None, "income", "income", False),
    ("liability", "asset", "card", "allocation", "allocation", False),
])
def test_import_backfill_uses_recurring_account_mapping_and_preserves_posting_values(
    db, source_type, destination_type, kind, line_type, entry_type, budgeted,
):
    import_client_data(ImportPayload(data={
        "accounts": [
            {"id": 10, "name": "source", "account_type": source_type, "liability_kind": kind},
            {"id": 11, "name": "destination", "account_type": destination_type},
        ],
        "recurring_transactions": [{
            "id": 20,
            "name": "legacy",
            "amount": 1234,
            "currency": "USD",
            "from_account_id": 10,
            "to_account_id": 11,
            "frequency": "Yearly",
            "day_of_month": 17,
            "month_of_year": 4,
            "start_period": "2026-04",
            "end_period": "2028-04",
            "next_due_date": "2027-04-17",
            "auto_post": False,
            "is_active": False,
        }],
    }), db, db.get(models.Client, 1))
    recurring = db.query(models.RecurringTransaction).one()
    entry = db.query(models.RegistryEntry).one()
    assert (entry.line_type, entry.entry_type) == (line_type, entry_type)
    assert entry.budget_account_id == (recurring.to_account_id if budgeted else None)
    assert entry.source_account_id == recurring.from_account_id
    assert entry.destination_account_id == recurring.to_account_id
    assert entry.source_recurring_transaction_id == recurring.id
    assert recurring.source_registry_entry_id == entry.id
    for field in ("name", "amount", "currency", "frequency", "day_of_month", "month_of_year", "start_period", "end_period", "is_active"):
        assert getattr(entry, field) == getattr(recurring, field)
    assert entry.generate_recurring is True
    assert entry.budget_active is True
    assert recurring.auto_post is False
    assert recurring.next_due_date.isoformat() == "2027-04-17"
